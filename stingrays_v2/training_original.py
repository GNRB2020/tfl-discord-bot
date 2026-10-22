"""Neon-backed training using the unchanged Phase 6 Sau and Phase 11 Tug rules/UI.
Only /dart/v2 routes; no legacy Sheets or TFL writes.
"""
import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from aiohttp import web
from .api import actor, pool, body, response, uid
from dart_engine import possible_checkout_darts

SCHEMA='stingrays_app'
OLD=Path(__file__).resolve().parents[1] / 'dart_ui'
KINDS=('sau','tug','bobs27')
TARGETS=[*range(1,21),25]

async def page(req):
    await actor(req)
    # Original scorer view, with Phase 6 and Phase 11 enhancements. The old login
    # request is suppressed: V2 sessions exclusively govern this page.
    html=(OLD/'index.html').read_text('utf-8')
    original="api('state').then(s=>{S=s;if(S.kind==='x01')showMatch();else if(S.kind==='sau')showSau();else screen('menuView')}).catch(()=>screen('loginView'));"
    if original not in html:
        raise web.HTTPInternalServerError(text='Original-Scorer-Vorlage wurde verändert; bitte Integration prüfen')
    html=html.replace(original,'')
    phase6=(OLD/'phase6.js').read_text('utf-8')
    # Ignore the old sessionStorage game ID: it belongs to the Sheets-backed app.
    phase6=phase6.replace("if (sessionStorage.getItem(gameKey)) {\n    api('state').then(s=>{S=s;if(s.kind==='sau')showSau();else if(s.kind==='x01')showMatch()}).catch(()=>{});\n  }",'')
    phase11=(OLD/'phase11.js').read_text('utf-8')
    end=phase11.rfind('})();')
    if end < 0:raise web.HTTPInternalServerError(text='Original-Tauziehen-Scorer nicht gefunden')
    phase11=phase11[:end]+"window.__v2ShowTug=showTug;\n"+phase11[end:]
    # Source is owned by the same repository; inline is deliberate to preserve
    # old lexical bindings and avoid modifying old production files.
    def inline(s):return '<script>'+s.replace('</script','<\\/script')+'</script>'
    html=html.replace('</body>',inline(phase6)+inline(phase11)+
       '<link rel="stylesheet" href="/dart/v2/assets/training_original.css">'+
       '<script src="/dart/v2/assets/training_original.js"></script></body>')
    return web.Response(text=html,content_type='text/html',headers={'Cache-Control':'no-store'})

async def players(req):
    await actor(req)
    async with pool(req).acquire() as db:
        rows=await db.fetch(f"SELECT id,display_name FROM {SCHEMA}.players WHERE is_active=true ORDER BY display_name")
    return response([dict(r) for r in rows])

def state_out(r,game_id,version,previous):
    k=r['kind'];s=copy.deepcopy(r)
    if k=='sau':
        s.update(kind='sau',game_id=str(game_id),sau_target=10,
            can_undo=previous is not None,completed_rounds=s['completed_rounds'],
            result={'player':s['name'],'rounds':s['completed_rounds'], 'sau':s['marks']['sau'],
                'checkout_counts':{str(i):s['marks'][str(i)] for i in range(4,13)},
                'checkouts':sum(s['marks'][str(i)] for i in range(4,13))} if s['finished'] else None)
    elif k=='tug':
        p=s['position'];s.update(kind='tug',game_id=str(game_id),remaining=[p,362-p],
            can_undo=previous is not None)
    else:
        s.update(kind='bobs27',game_id=str(game_id),can_undo=previous is not None)
    s['version']=version
    return s

async def new(req):
    a=await actor(req);d=await body(req);kind=str(d.get('kind',''))
    if kind not in KINDS:raise web.HTTPBadRequest(text='Trainingsart nicht verfügbar')
    pids=d.get('player_ids') or []
    if not isinstance(pids,list) or not 1<=len(pids)<=22 or len(set(pids))!=len(pids):
        raise web.HTTPBadRequest(text='1 bis 22 unterschiedliche Spieler auswählen')
    async with pool(req).acquire() as db:
        p=await db.fetch(f"SELECT id,display_name FROM {SCHEMA}.players WHERE id=ANY($1::uuid[]) AND is_active",[uid(x) for x in pids])
        byid={str(z['id']):z['display_name'] for z in p}
        if len(byid)!=len(pids):raise web.HTTPBadRequest(text='Unbekanntes oder inaktives Spielerprofil')
        names=[byid[str(x)] for x in pids]
        if kind=='sau':
            rounds=int(d.get('rounds',10))
            if not 1<=rounds<=10000:raise web.HTTPBadRequest(text='Rundenzahl 1–10000')
            state={'kind':'sau','name':' / '.join(names),'player_ids':[str(x) for x in pids],
                   'remaining':201,'visits':[],'marks':{'sau':0,**{str(i):0 for i in range(4,13)}},
                   'round':1,'completed_rounds':0,'rounds_target':rounds,'done':False,
                   'finished':False,'history':[]}
        elif kind=='tug':
            if len(names)!=2:raise web.HTTPBadRequest(text='Tauziehen braucht genau zwei Spieler')
            rounds=int(d.get('rounds',5))
            if not 1<=rounds<=100:raise web.HTTPBadRequest(text='Rundenzahl 1–100')
            state={'kind':'tug','names':names,'player_ids':[str(x) for x in pids],
                   'rounds':rounds,'round':1,'position':181,'current':0,'visits':[],
                   'wins':[0,0],'done':False,'finished':False}
        else:
            if len(names)!=1:raise web.HTTPBadRequest(text='Bobs 27 benötigt genau einen Spieler')
            state={'kind':'bobs27','name':names[0],'player_ids':[str(x) for x in pids],
                   'score':27,'target_index':0,'visits':[],'done':False,'finished':False}
        row=await db.fetchrow(f"INSERT INTO {SCHEMA}.training_games(account_id,kind,state) VALUES($1,$2,$3::jsonb) RETURNING id",a['id'],kind,json.dumps(state))
    return response(state_out(state,row['id'],0,None),201)

async def owned(db,mid,account,lock=False):
    q=f'SELECT * FROM {SCHEMA}.training_games WHERE id=$1 AND account_id=$2'
    if lock:q+=' FOR UPDATE'
    row=await db.fetchrow(q,mid,account['id'])
    if not row:raise web.HTTPNotFound(text='Training nicht gefunden')
    return row

async def get(req):
    a=await actor(req);mid=uid(req.match_info['gid'])
    async with pool(req).acquire() as db:row=await owned(db,mid,a)
    return response(state_out(json.loads(row['state']) if isinstance(row['state'],str) else row['state'],mid,row['version'],row['previous_state']))

def mutate(s,d):
    if s['finished']:raise ValueError('Training bereits abgeschlossen')
    k=s['kind']
    if k=='bobs27':
        hits=int(d.get('hits',-1))
        if hits not in (0,1,2,3):raise ValueError('Trefferzahl 0 bis 3')
        idx=s['target_index']
        if idx>=21:raise ValueError('Alle Doppel bereits gespielt')
        target=TARGETS[idx];value=target*2;delta=value*hits if hits else -value
        s['score']+=delta;s['visits'].append({'target':target,'hits':hits,'delta':delta,'score':s['score']})
        s['target_index']+=1
        if s['target_index']==21 or s['score']<0:s['finished']=s['done']=True
        return
    pts=int(d.get('points',-1))
    if not 0<=pts<=180:raise ValueError('Score 0 bis 180 erforderlich')
    if k=='tug':
        pl=s['current'];newpos=s['position']+(pts if pl==1 else -pts)
        s['visits'].append({'round':s['round'],'player':pl,'points':pts,
                            'before':s['position'],'after':newpos})
        s['position']=max(0,min(362,newpos))
        if newpos<=0 or newpos>=362:
            winner=0 if newpos<=0 else 1;s['wins'][winner]+=1
            if s['round']>=s['rounds']:s['finished']=s['done']=True
            else:s['round']+=1;s['position']=181;s['current']=0
        else:s['current']=1-pl
        return
    rest=s['remaining'];checkout=bool(d.get('checkout',False))
    darts=int(d.get('darts',3)) if checkout else 3
    if checkout:
        if pts!=rest or darts not in possible_checkout_darts(rest):raise ValueError('Checkout nicht möglich')
        total=sum(v['darts'] for v in s['visits'])+darts
        if not 4<=total<=12:raise ValueError('Sau-Checkout nur mit 4–12 Darts')
    if not checkout and (pts>=rest or rest-pts==1):pts=0
    s['visits'].append({'score':pts,'darts':darts,'checkout':checkout})
    s['history'].append({'round':s['round'],'score':pts,'rest_after':rest-pts})
    s['remaining']-=pts
    if checkout:s['marks'][str(sum(v['darts'] for v in s['visits']))]+=1;s['done']=True
    elif len(s['visits'])>=4:s['marks']['sau']+=1;s['done']=True
    if s['done']:
        s['completed_rounds']+=1
        s['finished']=(s['completed_rounds']>=s['rounds_target'] and s['marks']['sau']>=10)
        if not s['finished']:
            s['round']+=1;s['remaining']=201;s['visits']=[];s['done']=False

async def action(req):
    a=await actor(req);d=await body(req);mid=uid(req.match_info['gid'])
    async with pool(req).acquire() as db:
      async with db.transaction():
        row=await owned(db,mid,a,True)
        s=copy.deepcopy(json.loads(row['state']) if isinstance(row['state'],str) else row['state'])
        if req.match_info['action']=='undo':
            prev=row['previous_state']
            if not prev:raise web.HTTPConflict(text='Keine Aufnahme zum Zurücknehmen')
            new=json.loads(prev) if isinstance(prev,str) else prev
            await db.execute(f'''UPDATE {SCHEMA}.training_games SET state=$2::jsonb,previous_state=NULL,
                  version=version+1,finished=$3,updated_at=now() WHERE id=$1''',mid,json.dumps(new),new['finished'])
            return response(state_out(new,mid,row['version']+1,None))
        if req.match_info['action']=='next-sau':
            if s['kind']!='sau' or not s['done'] or s['finished']:raise web.HTTPConflict(text='Kein neuer Durchgang')
            s['round']+=1;s['remaining']=201;s['visits']=[];s['done']=False
        elif req.match_info['action']=='throw':
            try:mutate(s,d)
            except (ValueError,KeyError,TypeError) as e:raise web.HTTPBadRequest(text=str(e))
        else:raise web.HTTPNotFound()
        await db.execute(f'''UPDATE {SCHEMA}.training_games SET state=$2::jsonb,previous_state=$3::jsonb,
            version=version+1,finished=$4,updated_at=now() WHERE id=$1''',mid,json.dumps(s),json.dumps(row['state']) if not isinstance(row['state'],str) else row['state'],s['finished'])
        return response(state_out(s,mid,row['version']+1,row['state']))

def register(app):
    app.router.add_get('/dart/v2/training/scorer/',page)
    app.router.add_get('/dart/v2/api/training-games/players',players)
    app.router.add_post('/dart/v2/api/training-games',new)
    app.router.add_get('/dart/v2/api/training-games/{gid}',get)
    app.router.add_post('/dart/v2/api/training-games/{gid}/{action:throw|undo|next-sau}',action)
