"""Stingrays training portal phase 6. In-memory TEST ONLY; not persistent.

One browser tab owns one game_id. Different tablets/tabs therefore have isolated matches.
Server-side owner checks and session cookies protect every game operation.
"""
from __future__ import annotations
import asyncio
import copy
import hmac
import os
import secrets
import time
from pathlib import Path
from aiohttp import web
from dart_engine import Match, Rules, possible_checkout_darts
from dart_training_tournaments import register_training_tournaments, restore_from_sheet

ROOT = Path(__file__).resolve().parent
SESSIONS: dict[str, tuple[str, float]] = {}
GAMES: dict[str, dict] = {}
LAST_ACTION: dict[str, dict] = {}
LOCK = asyncio.Lock()
SESSION_TTL = 8 * 3600
SAU_TARGET = 10


def _origin_ok(request):
    origin = request.headers.get('Origin')
    if not origin:
        return True
    return origin == f'https://{request.host}' or origin == f'{request.scheme}://{request.host}'


def _user(request):
    token = request.cookies.get('stingrays_session', '')
    record = SESSIONS.get(token)
    if record and record[1] > time.time():
        return token
    return None


def _auth(request):
    if not _origin_ok(request):
        raise web.HTTPForbidden(text='Ungültige Herkunft')
    token = _user(request)
    if not token:
        raise web.HTTPUnauthorized(text='Bitte anmelden')
    return token


def _owned(request, user):
    game_id = request.headers.get('X-Dart-Game-ID', '').strip()
    record = GAMES.get(game_id)
    if not record or record['owner'] != user:
        return None
    return record


def _sau_state(r):
    return {
        'kind':'sau', 'game_id':r['game_id'], 'name':r['name'],
        'remaining':r['remaining'], 'visits':r['visits'],
        'marks':r['marks'], 'round':r['round'], 'done':r['done'],
        'finished':r['finished'], 'rounds_target':r['rounds_target'],
        'sau_target':SAU_TARGET, 'completed_rounds':r['completed_rounds'],
        'result':_sau_result(r) if r['finished'] else None,
        'history':r.get('history',[])[-12:],
        'can_undo':r['game_id'] in LAST_ACTION,
    }


def _sau_result(r):
    return {'player':r['name'], 'rounds':r['completed_rounds'],
            'sau':r['marks']['sau'], 'checkout_counts':{str(i):r['marks'][str(i)] for i in range(4,13)},
            'checkouts':sum(r['marks'][str(i)] for i in range(4,13))}


def _state(r):
    if not r:
        return {'kind':None}
    if r['kind'] == 'sau':
        return _sau_state(r)
    if r['kind']=='tug':
        return {'kind':'tug','game_id':r['game_id'],'names':r['names'], 'rounds':r['rounds'],
          'round':r['round'],'position':r['position'], 'remaining':[r['position'],362-r['position']],
          'current':r['current'],'visits':r['visits'][-12:], 'wins':r['wins'],
          'done':r['done'], 'finished':r['finished'], 'can_undo':r['game_id'] in LAST_ACTION}
    m = r['match']
    stats = m.summary()
    rest = m.remaining[m.current]
    return {'kind':'x01','game_id':r['game_id'], 'names':list(m.names),
            'remaining':m.remaining[:], 'legs':m.legs[:], 'sets':m.sets[:],
            'current':m.current, 'done':m.done, 'leg_number':m.leg_number,
            'rules':vars(m.rules), 'can_checkout':possible_checkout_darts(rest) if rest <= 170 and not m.done else [],
            'current_stats':stats['players'], 'last':[vars(v) for v in m.visits[-8:]],
            'summary':stats if m.done else None, 'starter':r.get('starter',0),
            'history':[vars(v) for v in m.visits[-12:]], 'can_undo':r['game_id'] in LAST_ACTION}


async def home(request):
    # Preserve the existing phase-5 UI. The upgrade script patches only Sau UX.
    html = (ROOT/'dart_ui'/'index.html').read_text(encoding='utf-8')
    injection = '<script src="/dart/phase6.js" defer></script><script src="/dart/tournament_menu.js" defer></script><script src="/dart/phase11.js" defer></script>'
    html = html.replace('</body>', injection + '</body>')
    return web.Response(text=html, content_type='text/html', charset='utf-8',headers={'Cache-Control':'no-store'})


async def phase6_js(request):
    return web.FileResponse(ROOT/'dart_ui'/'phase6.js',headers={'Cache-Control':'no-store'})


async def phase11_js(request):
    return web.FileResponse(ROOT/'dart_ui'/'phase11.js', headers={'Cache-Control':'no-store'})


async def login(request):
    if not _origin_ok(request):
        raise web.HTTPForbidden()
    data = await request.json()
    username = str(data.get('username',''))
    pin = str(data.get('pin',''))
    expected = os.environ.get('DART_ADMIN_PIN','')
    if len(expected) < 10:
        return web.json_response({'error':'DART_ADMIN_PIN in Render konfigurieren (mind. 10 Zeichen)'},status=503)
    if not (hmac.compare_digest(username.casefold(),'stingrays') and hmac.compare_digest(pin,expected)):
        await asyncio.sleep(.7)
        return web.json_response({'error':'Anmeldung fehlgeschlagen'},status=401)
    token=secrets.token_urlsafe(32)
    SESSIONS[token]=('Stingrays',time.time()+SESSION_TTL)
    response=web.json_response({'user':'Stingrays'})
    response.set_cookie('stingrays_session',token,httponly=True,secure=True,samesite='Strict',max_age=SESSION_TTL,path='/dart/')
    return response


async def logout(request):
    user=_auth(request)
    SESSIONS.pop(user,None)
    # Only this session's games. Other devices are unaffected.
    for gid in [gid for gid,r in GAMES.items() if r['owner']==user]:
        GAMES.pop(gid,None)
        LAST_ACTION.pop(gid,None)
    resp=web.json_response({'ok':True})
    resp.del_cookie('stingrays_session',path='/dart/')
    return resp


async def state(request):
    user=_auth(request)
    return web.json_response({'user':'Stingrays',**_state(_owned(request,user))})


async def new_match(request):
    user=_auth(request)
    data=await request.json()
    async with LOCK:
        try:
            kind=data.get('kind','x01')
            game_id=secrets.token_urlsafe(18)
            if kind=='sau':
                rounds=int(data.get('rounds',10))
                if rounds < 1 or rounds > 10000:
                    raise ValueError('Rundenzahl muss zwischen 1 und 10000 liegen')
                r={'kind':'sau','owner':user,'game_id':game_id,
                   'name':str(data.get('a') or 'Spieler 1')[:45],
                   'remaining':201,'visits':[],
                   'marks':{'sau':0,**{str(i):0 for i in range(4,13)}},
                   'round':1,'completed_rounds':0,'rounds_target':rounds,
                   'done':False,'finished':False,'history':[]}
            elif kind=='tug':
                rounds=int(data.get('rounds',5))
                if not 1<=rounds<=100:raise ValueError('Rundenzahl 1 bis 100')
                r={'kind':'tug','owner':user,'game_id':game_id,
                   'names':[str(data.get('a') or 'Spieler 1')[:45],str(data.get('b') or 'Spieler 2')[:45]],
                   'rounds':rounds,'round':1,'position':181,'current':0, 'visits':[],
                   'wins':[0,0],'done':False,'finished':False}
            elif kind=='x01':
                mode=data.get('mode','legs')
                start=int(data.get('start_score',501))
                n=int(data.get('best_of',5))
                per_set=int(data.get('legs_per_set',5))
                if start not in (170,301,501,701,1001,5001,10001):
                    raise ValueError('Ungültige Startpunkte')
                if not 1<=n<=101 or not 1<=per_set<=101:
                    raise ValueError('Best-of muss zwischen 1 und 101 liegen')
                rules=Rules(start_score=start,mode=mode,max_legs=n,best_of_sets=n,
                            best_of_legs_per_set=per_set,allow_draw=(n%2==0))
                names=(str(data.get('a') or 'Spieler 1')[:45],str(data.get('b') or 'Spieler 2')[:45])
                starter=int(data.get('starter',0))
                if starter not in (0,1):raise ValueError('Ungültiger Anwurf')
                match=Match(rules,names)
                match.current=starter;match.first_throw=starter
                r={'kind':'x01','owner':user,'game_id':game_id,'match':match,'starter':starter}
            else:
                raise ValueError('Trainingsmodus nicht verfügbar')
        except (ValueError,TypeError) as exc:
            return web.json_response({'error':str(exc)},status=400)
        GAMES[game_id]=r
        LAST_ACTION.pop(game_id,None)
        return web.json_response(_state(r))


async def throw(request):
    user=_auth(request)
    data=await request.json()
    async with LOCK:
        r=_owned(request,user)
        if not r:
            return web.json_response({'error':'Kein Spiel für diesen Tab. Bitte neues Spiel starten.'},status=409)
        before=copy.deepcopy(r)
        try:
            if r['kind']=='x01':
                m=r['match']
                m.submit(m.current,int(data['points']),darts=int(data.get('darts',3)),
                         checkout=bool(data.get('checkout',False)),
                         checkout_attempts=int(data.get('checkout_attempts',0)),
                         bullfinish=bool(data.get('bullfinish',False)))
            elif r['kind']=='tug':
                if r['finished']:raise ValueError('Training beendet')
                points=int(data['points'])
                if not 0<=points<=180:raise ValueError('Ungültiger Score')
                player=r['current'];new_position=r['position']+ (points if player==1 else -points)
                r['visits'].append({'round':r['round'],'player':player,'points':points,'before':r['position'],'after':new_position})
                r['position']=max(0,min(362,new_position))
                if new_position<=0 or new_position>=362:
                    winner=0 if new_position<=0 else 1
                    r['wins'][winner]+=1
                    if r['round']>=r['rounds']:r['finished']=True;r['done']=True
                    else:r['round']+=1;r['position']=181;r['current']=0
                else:r['current']=1-player
            else:
                if r['finished'] or r['done']:
                    raise ValueError('Durchgang beendet')
                points=int(data['points'])
                if not 0<=points<=180:
                    raise ValueError('Ungültige Punktzahl')
                rest=r['remaining']
                checkout=bool(data.get('checkout',False))
                darts=int(data.get('darts',3)) if checkout else 3
                if checkout:
                    if points!=rest or darts not in possible_checkout_darts(rest):
                        raise ValueError('Checkout nicht möglich')
                    total=sum(v['darts'] for v in r['visits'])+darts
                    if not 4<=total<=12:
                        raise ValueError('Checkout nur mit 4 bis 12 Darts')
                if points>=rest and not checkout:
                    points=0  # Bust
                if rest-points==1:
                    points=0  # Bust
                r['visits'].append({'score':points,'darts':darts,'checkout':checkout})
                r.setdefault('history',[]).append({'round':r['round'],'score':points,'rest_after':rest-points})
                r['remaining']-=points
                total=sum(v['darts'] for v in r['visits'])
                if checkout:
                    r['marks'][str(total)]+=1
                    r['done']=True
                elif len(r['visits'])>=4:
                    r['marks']['sau']+=1
                    r['done']=True
                if r['done']:
                    r['completed_rounds']+=1
                    r['finished']=(r['completed_rounds']>=r['rounds_target'] and r['marks']['sau']>=SAU_TARGET)
                    # Nach einem Sau-Strich sofort nächste Runde, sofern Training noch läuft.
                    if not r['finished']:
                        r['round']+=1
                        r['remaining']=201
                        r['visits']=[]
                        r['done']=False
        except (ValueError,TypeError,KeyError) as exc:
            return web.json_response({'error':str(exc)},status=400)
        LAST_ACTION[r['game_id']]=before
        return web.json_response(_state(r))


async def undo(request):
    user=_auth(request)
    async with LOCK:
        r=_owned(request,user)
        if not r:
            return web.json_response({'error':'Spiel nicht gefunden'},status=409)
        gid=r['game_id']
        previous=LAST_ACTION.pop(gid,None)
        if previous is None:
            return web.json_response({'error':'Keine Aufnahme zum Rückgängigmachen vorhanden'},status=409)
        GAMES[gid]=previous
        return web.json_response(_state(previous))


async def next_sau(request):
    user=_auth(request)
    async with LOCK:
        r=_owned(request,user)
        if not r or r['kind']!='sau' or not r['done'] or r['finished']:
            return web.json_response({'error':'Kein weiterer Durchgang möglich'},status=409)
        LAST_ACTION.pop(r['game_id'],None)  # A new voluntary round closes the previous undo window.
        r['round']+=1
        r['remaining']=201
        r['visits']=[]
        r['done']=False
        return web.json_response(_state(r))


async def tournaments_page(request):
    _auth(request)
    return web.FileResponse(ROOT / 'dart_ui' / 'tournaments.html', headers={'Cache-Control':'no-store'})

async def tournament_script(request):
    _auth(request)
    return web.FileResponse(ROOT / 'dart_ui' / 'tournaments.js', headers={'Cache-Control':'no-store'})

async def tournament11_script(request):
    _auth(request)
    return web.FileResponse(ROOT / 'dart_ui' / 'tournaments11.js',headers={'Cache-Control':'no-store'})

async def menu_script(request):
    return web.FileResponse(ROOT / 'dart_ui' / 'tournament_menu.js', headers={'Cache-Control':'no-store'})

def register_dart_render_preview(app):
    if len(os.environ.get('DART_ADMIN_PIN',''))<10:
        print('[STINGRAYS] Warning: DART_ADMIN_PIN is missing/too short')
    app.router.add_get('/dart/',home)
    app.router.add_get('/dart/phase6.js',phase6_js)
    app.router.add_get('/dart/phase11.js',phase11_js)
    app.router.add_get('/dart/tournament_menu.js',menu_script)
    app.router.add_get('/dart/tournaments/',tournaments_page)
    app.router.add_get('/dart/tournaments.js',tournament_script)
    app.router.add_get('/dart/tournaments11.js',tournament11_script)
    register_training_tournaments(app,_auth)
    async def _restore_tournaments(application):
        await restore_from_sheet()
    app.on_startup.append(_restore_tournaments)
    app.router.add_post('/dart/api/login',login)
    app.router.add_post('/dart/api/logout',logout)
    app.router.add_get('/dart/api/state',state)
    app.router.add_post('/dart/api/new',new_match)
    app.router.add_post('/dart/api/throw',throw)
    app.router.add_post('/dart/api/undo',undo)
    app.router.add_post('/dart/api/next-sau',next_sau)
    print('[STINGRAYS] Phase 7 registered at /dart/')
