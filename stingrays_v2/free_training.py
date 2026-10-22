"""Free X01 training matches. Not linked to any competition or its standings."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from aiohttp import web
from dart_engine import Match, Rules, Visit, possible_checkout_darts
from .rules import mode_rules
from .api import actor, body, pool, uid, as_json, response, pack_game


def unpack(row):
    state=as_json(row['state']);rules=as_json(row['rules'])
    g=Match(Rules(**{**rules,**state.get('rules',{})}), (row['player1'],row['player2']))
    for key in ('remaining','legs','sets','current','first_throw','leg_number','done'):
        if key in state:setattr(g,key,state[key])
    g.visits=[Visit(**v) for v in state.get('visits',[])]
    return g


async def create(req):
    a=await actor(req);d=await body(req)
    own=a['player_id']
    if own is None:raise web.HTTPForbidden(text='Bitte ein Spielerprofil mit deinem Konto verknüpfen')
    other=uid(d.get('other_id'))
    if own==other:raise web.HTTPBadRequest(text='Zwei verschiedene Spieler erforderlich')
    requested=d.get('rules') or {}
    if not isinstance(requested,dict):raise web.HTTPBadRequest(text='Ungültige Regeln')
    try:
        configured=mode_rules('training_tournament','groups',overrides=requested)
        Rules(**configured)
    except (ValueError,TypeError,KeyError) as exc:raise web.HTTPBadRequest(text=str(exc))
    async with pool(req).acquire() as db:
        if not await db.fetchval('SELECT EXISTS(SELECT 1 FROM stingrays_app.players WHERE id=$1 AND is_active)',other):
            raise web.HTTPBadRequest(text='Gegnerprofil nicht vorhanden')
        record=await db.fetchrow('''INSERT INTO stingrays_app.free_x01_matches
            (created_by,player1_id,player2_id,rules) VALUES($1,$2,$3,$4::jsonb) RETURNING id''',a['id'],own,other,json.dumps(configured))
    return response({'id':record['id']},201)


async def get_row(db,mid,lock=False):
    row=await db.fetchrow('''SELECT m.*,p1.display_name AS player1,p2.display_name AS player2
      FROM stingrays_app.free_x01_matches m JOIN stingrays_app.players p1 ON p1.id=m.player1_id
      JOIN stingrays_app.players p2 ON p2.id=m.player2_id WHERE m.id=$1'''+(' FOR UPDATE OF m' if lock else ''),mid)
    if not row:raise web.HTTPNotFound(text='Training nicht gefunden')
    return row


def access(a,row):
    if a['role'] not in ('admin','tournament') and a['id']!=row['created_by']:
        raise web.HTTPForbidden(text='Nur das eigene freie Training bedienen')


async def detail(req):
    a=await actor(req);mid=uid(req.match_info['mid'])
    async with pool(req).acquire() as db:row=await get_row(db,mid)
    access(a,row);r=dict(row)
    r['can_score']=True
    if row['status']=='finished':r['summary']=unpack(row).summary()
    return response(r)


async def start(req):
    a=await actor(req);d=await body(req);mid=uid(req.match_info['mid'])
    async with pool(req).acquire() as db:
      async with db.transaction():
        r=await get_row(db,mid,True);access(a,r)
        if r['status']=='finished':raise web.HTTPConflict(text='Training abgeschlossen')
        g=unpack(r)
        if not as_json(r['state']):
            starter=int(d.get('starter',0))
            if starter not in (0,1):raise web.HTTPBadRequest(text='Startspieler ungültig')
            g.current=g.first_throw=starter
        state=pack_game(g)
        await db.execute('''UPDATE stingrays_app.free_x01_matches SET status='running',state=$2::jsonb
           WHERE id=$1''',mid,json.dumps(state))
    return response({'state':state,'version':r['state_version']})


async def throw(req):
    a=await actor(req);d=await body(req);mid=uid(req.match_info['mid'])
    async with pool(req).acquire() as db:
      async with db.transaction():
        r=await get_row(db,mid,True);access(a,r)
        if r['status']!='running':raise web.HTTPConflict(text='Training nicht gestartet')
        if int(d.get('version',-1))!=r['state_version']:raise web.HTTPConflict(text='Spielstand verändert – bitte neu laden')
        g=unpack(r)
        try:g.submit(g.current,int(d['points']),darts=int(d.get('darts',3)),checkout=bool(d.get('checkout',False)),
                     bullfinish=bool(d.get('bullfinish',False)),checkout_attempts=int(d.get('checkout_attempts',0)))
        except (KeyError,ValueError) as exc:raise web.HTTPBadRequest(text=str(exc))
        state=pack_game(g)
        await db.execute('''UPDATE stingrays_app.free_x01_matches SET state=$2::jsonb,state_version=state_version+1,
           status=$3,finished_at=CASE WHEN $4 THEN now() ELSE finished_at END WHERE id=$1''',
           mid,json.dumps(state),'finished' if g.done else 'running',g.done)
    return response({'state':state,'version':r['state_version']+1,'summary':g.summary() if g.done else None})


async def undo(req):
    a=await actor(req);d=await body(req);mid=uid(req.match_info['mid'])
    async with pool(req).acquire() as db:
      async with db.transaction():
        r=await get_row(db,mid,True);access(a,r)
        if r['status']!='running':raise web.HTTPConflict(text='Nur laufende Trainings korrigieren')
        if int(d.get('version',-1))!=r['state_version']:raise web.HTTPConflict(text='Spielstand verändert')
        state=as_json(r['state'])
        if not state.get('visits'):raise web.HTTPConflict(text='Keine Aufnahme vorhanden')
        # Replay all visits except the last to restore legs, sets, starter, and darts accurately.
        all_visits=state['visits'][:-1]
        g=Match(Rules(**as_json(r['rules'])),(r['player1'],r['player2']))
        g.current=g.first_throw=int(state.get('first_throw',0))
        for v in all_visits:
            g.submit(v['player'],v['score'],darts=v.get('darts',3),checkout=v.get('checkout',False),
                     bullfinish=v.get('bullfinish',False),checkout_attempts=v.get('checkout_attempts',0))
        new_state=pack_game(g)
        await db.execute('UPDATE stingrays_app.free_x01_matches SET state=$2::jsonb,state_version=state_version+1 WHERE id=$1',mid,json.dumps(new_state))
    return response({'state':new_state,'version':r['state_version']+1})


def register(app):
    app.router.add_post('/dart/v2/api/free-x01',create)
    app.router.add_get('/dart/v2/api/free-x01/{mid}',detail)
    app.router.add_post('/dart/v2/api/free-x01/{mid}/start',start)
    app.router.add_post('/dart/v2/api/free-x01/{mid}/throw',throw)
    app.router.add_post('/dart/v2/api/free-x01/{mid}/undo',undo)
