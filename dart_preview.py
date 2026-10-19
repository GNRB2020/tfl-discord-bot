"""Phase-2 test scorer routes. Matches remain process-local; no production persistence."""
from __future__ import annotations
import os
from pathlib import Path
from aiohttp import web
from dart_engine import Match, Rules, possible_checkout_darts

ROOT = Path(__file__).resolve().parent
MATCH = None

def view():
    m = MATCH
    stats = m.summary()
    rest = m.remaining[m.current]
    options = possible_checkout_darts(rest) if m.rules.double_out else list(range(1, 4))
    return {
        'names': list(m.names), 'remaining': m.remaining[:], 'legs': m.legs[:],
        'sets': m.sets[:], 'current': m.current, 'done': m.done,
        'leg_number': m.leg_number, 'rules': vars(m.rules),
        'can_checkout': options if rest <= 170 and not m.done else [],
        'current_stats': stats['players'],
        'last': [vars(v) for v in m.visits[-6:]],
        'summary': stats if m.done else None,
    }

async def page(request):
    return web.FileResponse(ROOT/'dart_ui'/'index.html', headers={'Cache-Control':'no-store'})

async def status(request):
    return web.json_response(view())

async def reset(request):
    global MATCH
    data = await request.json()
    if MATCH and MATCH.visits and not MATCH.done:
        return web.json_response({'error':'Aktives Spiel kann nicht zurückgesetzt werden.'}, status=409)
    try:
        names=(str(data.get('a','Spieler A'))[:48],str(data.get('b','Spieler B'))[:48])
        rules=Rules(start_score=int(data.get('start_score',501)),mode=data.get('mode','legs'),
                    max_legs=int(data.get('max_legs',6)),allow_draw=bool(data.get('allow_draw',True)),
                    best_of_sets=int(data.get('best_of_sets',5)),
                    best_of_legs_per_set=int(data.get('best_of_legs_per_set',5)))
        MATCH=Match(rules,names)
        return web.json_response(view())
    except (ValueError,TypeError,KeyError) as e:
        return web.json_response({'error':str(e)},status=400)

async def throw(request):
    global MATCH
    try:
        data=await request.json()
        MATCH.submit(MATCH.current,int(data['points']), darts=int(data.get('darts',3)),
                     checkout=bool(data.get('checkout',False)),
                     checkout_attempts=int(data.get('checkout_attempts',0)),
                     bullfinish=bool(data.get('bullfinish',False)))
        return web.json_response(view())
    except (ValueError,TypeError,KeyError) as e:
        return web.json_response({'error':str(e)},status=400)

def create_app():
    global MATCH
    MATCH=Match(Rules(max_legs=6,allow_draw=True),('Spieler A','Spieler B'))
    app=web.Application(client_max_size=1024*16)
    app.router.add_get('/dart/',page)
    app.router.add_get('/dart/api/state',status)
    app.router.add_post('/dart/api/new',reset)
    app.router.add_post('/dart/api/throw',throw)
    return app

if __name__=='__main__':
    web.run_app(create_app(),host='127.0.0.1',port=int(os.getenv('DART_PREVIEW_PORT','8765')))
