"""Stingrays Phase 5 – protected tablet training portal on the existing aiohttp API.
All state is process-local, for testing only. Configure DART_ADMIN_PIN in Render.
"""
from __future__ import annotations
import asyncio
import hashlib
import hmac
import os
import secrets
import time
from collections import Counter
from pathlib import Path
from aiohttp import web
from dart_engine import Match, Rules, possible_checkout_darts

ROOT = Path(__file__).resolve().parent
SESSIONS = {}
MATCHES = {}
LOCK = asyncio.Lock()
SESSION_TTL = 8 * 3600


def _user(request):
    token = request.cookies.get('stingrays_session', '')
    record = SESSIONS.get(token)
    if record and record[1] > time.time():
        return token
    return None


def _check_origin(request):
    origin = request.headers.get('Origin')
    if not origin:
        return True
    expected = f'{request.scheme}://{request.host}'
    # Proxy-aware: browsers send the public HTTPS origin, request.host is correct on Render.
    return hmac.compare_digest(origin, expected) or (request.headers.get('X-Forwarded-Proto') == 'https' and origin == f'https://{request.host}')


def _secure(request):
    if not _check_origin(request):
        raise web.HTTPForbidden(text='Ungültige Herkunft')
    token = _user(request)
    if not token:
        raise web.HTTPUnauthorized(text='Bitte anmelden')
    return token


def _match_state(session):
    record = MATCHES.get(session)
    if not record:
        return {'kind': None}
    if record['kind'] == 'sau':
        return {'kind': 'sau', **{k:v for k,v in record.items() if k != 'kind'}}
    m = record['match']
    stats = m.summary()
    rest = m.remaining[m.current]
    return {'kind':'x01', 'names':list(m.names), 'remaining':m.remaining[:],
            'legs':m.legs[:], 'sets':m.sets[:], 'current':m.current,
            'done':m.done, 'leg_number':m.leg_number, 'rules':vars(m.rules),
            'can_checkout':possible_checkout_darts(rest) if rest <= 170 and not m.done else [],
            'current_stats':stats['players'],
            'last':[vars(v) for v in m.visits[-8:]],
            'summary':stats if m.done else None}


async def home(request):
    return web.FileResponse(ROOT / 'dart_ui' / 'index.html', headers={'Cache-Control':'no-store'})


async def login(request):
    if not _check_origin(request):
        raise web.HTTPForbidden()
    data = await request.json()
    username = str(data.get('username',''))
    pin = str(data.get('pin',''))
    expected = os.environ.get('DART_ADMIN_PIN', '')
    if not expected or len(expected) < 10:
        return web.json_response({'error':'DART_ADMIN_PIN in Render konfigurieren (mind. 10 Zeichen)'},status=503)
    if not (hmac.compare_digest(username.casefold(), 'stingrays') and hmac.compare_digest(pin, expected)):
        # Minimal slowing down brute-force attempts; additional perimeter rate limiting recommended.
        await asyncio.sleep(0.7)
        return web.json_response({'error':'Anmeldung fehlgeschlagen'},status=401)
    token = secrets.token_urlsafe(32)
    SESSIONS[token] = ('Stingrays', time.time()+SESSION_TTL)
    resp = web.json_response({'user':'Stingrays'})
    resp.set_cookie('stingrays_session', token, httponly=True, secure=True,
                    samesite='Strict', max_age=SESSION_TTL, path='/dart/')
    return resp


async def logout(request):
    token = _secure(request)
    SESSIONS.pop(token, None)
    resp = web.json_response({'ok':True})
    resp.del_cookie('stingrays_session',path='/dart/')
    return resp


async def state(request):
    token = _secure(request)
    return web.json_response({'user':'Stingrays', **_match_state(token)})


async def new_match(request):
    token = _secure(request)
    data = await request.json()
    async with LOCK:
        if token in MATCHES and not MATCHES[token].get('kind') == 'sau':
            old = MATCHES[token].get('match')
            if old and old.visits and not old.done:
                return web.json_response({'error':'Laufendes Match erst beenden'},status=409)
        try:
            kind = data.get('kind', 'x01')
            if kind == 'sau':
                MATCHES[token] = {'kind':'sau','name':str(data.get('a') or 'Spieler 1')[:45],
                                  'remaining':201,'visits':[], 'marks':{'sau':0, **{str(i):0 for i in range(4,13)}},
                                  'round':1, 'done':False}
            elif kind == 'x01':
                mode = data.get('mode','legs')
                start = int(data.get('start_score',501))
                if start not in (170,301,501,701,1001,5001,10001):
                    raise ValueError('Ungültige Startpunkte')
                n = int(data.get('best_of',5))
                per_set = int(data.get('legs_per_set',5))
                if not 1 <= n <= 101 or not 1 <= per_set <= 101:
                    raise ValueError('Best-of muss zwischen 1 und 101 liegen')
                rules = Rules(start_score=start, mode=mode, max_legs=n,
                    best_of_sets=n, best_of_legs_per_set=per_set,
                    allow_draw=(n % 2 == 0))
                names=(str(data.get('a') or 'Spieler 1')[:45],str(data.get('b') or 'Spieler 2')[:45])
                MATCHES[token]={'kind':'x01','match':Match(rules,names)}
            else:
                raise ValueError('Trainingsmodus nicht verfügbar')
        except (ValueError, TypeError) as exc:
            return web.json_response({'error':str(exc)},status=400)
        return web.json_response(_match_state(token))


async def throw(request):
    token = _secure(request)
    data = await request.json()
    async with LOCK:
        record = MATCHES.get(token)
        if not record:
            return web.json_response({'error':'Kein Match gestartet'},status=409)
        try:
            if record['kind'] == 'x01':
                m = record['match']
                m.submit(m.current,int(data['points']),darts=int(data.get('darts',3)),
                     checkout=bool(data.get('checkout',False)),
                     checkout_attempts=int(data.get('checkout_attempts',0)),
                     bullfinish=bool(data.get('bullfinish',False)))
            else:
                if record['done']:
                    raise ValueError('Durchgang abgeschlossen – neuen Durchgang starten')
                points=int(data['points'])
                if points < 0 or points > 180:
                    raise ValueError('Ungültige Punktzahl')
                rest=record['remaining']
                checkout=bool(data.get('checkout',False))
                darts=int(data.get('darts',3)) if checkout else 3
                if checkout:
                    if points != rest or darts not in possible_checkout_darts(rest):
                        raise ValueError('Checkout nicht möglich')
                    total = sum(v['darts'] for v in record['visits']) + darts
                    if not 4 <= total <= 12:
                        raise ValueError('Gegen die Sau: Checkout nur mit 4 bis 12 Darts')
                if points >= rest and not checkout:
                    if points == rest:
                        raise ValueError('Bitte CHECK verwenden')
                    points=0  # Bust
                if rest-points == 1:
                    points=0  # Bust
                record['visits'].append({'score':points,'darts':darts,'checkout':checkout})
                record['remaining'] -= points
                total=sum(v['darts'] for v in record['visits'])
                if checkout:
                    record['marks'][str(total)]+=1
                    record['done']=True
                elif len(record['visits']) >= 4:
                    record['marks']['sau']+=1
                    record['done']=True
        except (ValueError,TypeError,KeyError) as exc:
            return web.json_response({'error':str(exc)},status=400)
        return web.json_response(_match_state(token))


async def next_sau(request):
    token=_secure(request)
    async with LOCK:
        r=MATCHES.get(token)
        if not r or r['kind'] != 'sau' or not r['done']:
            return web.json_response({'error':'Durchgang noch nicht beendet'},status=409)
        r['round']+=1
        r['remaining']=201
        r['visits']=[]
        r['done']=False
        return web.json_response(_match_state(token))


def register_dart_render_preview(app: web.Application):
    if len(os.environ.get('DART_ADMIN_PIN','')) < 10:
        print('[STINGRAYS] Warning: DART_ADMIN_PIN is missing/too short; login disabled')
    app.router.add_get('/dart/', home)
    app.router.add_post('/dart/api/login',login)
    app.router.add_post('/dart/api/logout',logout)
    app.router.add_get('/dart/api/state',state)
    app.router.add_post('/dart/api/new',new_match)
    app.router.add_post('/dart/api/throw',throw)
    app.router.add_post('/dart/api/next-sau',next_sau)
    print('[STINGRAYS] Phase 5 portal registered at /dart/')
