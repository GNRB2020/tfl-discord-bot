"""Shared, process-local training tournaments. Do not use for persistent competitions."""
from __future__ import annotations
import asyncio
import copy
import secrets
from dataclasses import asdict
from dart_engine import Visit
from dart_sheet_store import save as sheet_save, load_all as sheet_load
from datetime import datetime, timezone
from aiohttp import web
from dart_engine import Match, Rules, possible_checkout_darts

TOURNAMENTS = {}
LOCK = asyncio.Lock()

def _pack_match(m):
    if m is None:return None
    return {'rules':asdict(m.rules),'names':list(m.names),'remaining':m.remaining[:],
            'legs':m.legs[:],'sets':m.sets[:],'visits':[asdict(v) for v in m.visits],
            'current':m.current,'first_throw':m.first_throw,'leg_number':m.leg_number,'done':m.done}


def _unpack_match(raw):
    if raw is None:return None
    m=Match(Rules(**raw['rules']),tuple(raw['names']))
    for name in ('remaining','legs','sets','current','first_throw','leg_number','done'):
        setattr(m,name,raw[name])
    m.visits=[Visit(**v) for v in raw['visits']]
    return m


def _pack_tournament(t):
    return {**{k:v for k,v in t.items() if k!='matches'},
            'matches':[{**{k:v for k,v in m.items() if k not in ('game','undo')},
                        'game':_pack_match(m['game']), 'undo':_pack_match(m['undo'])} for m in t['matches']]}


def _unpack_tournament(raw):
    t={**raw}
    t['matches']=[{**m,'game':_unpack_match(m['game']),
                   'undo':_unpack_match(m.get('undo'))} for m in raw['matches']]
    return t


async def restore_from_sheet():
    data=await sheet_load()
    print(f'[DART SHEETS] Lade {len(data)} Snapshot-Zeilen aus Google Sheets',flush=True)
    loaded={}
    for key,raw in data.items():
        try:
            tournament=_unpack_tournament(raw)
            if tournament['id']==key:loaded[key]=tournament
        except (ValueError,KeyError,TypeError) as exc:
            print(f'[DART SHEETS] Snapshot {key} fehlerhaft: {exc}')
    async with LOCK:
        TOURNAMENTS.update(loaded)
    print(f'[DART SHEETS] {len(loaded)} Turniere wiederhergestellt: {list(loaded)}',flush=True)


async def _persist(t):
    await sheet_save(t['id'],_pack_tournament(t))
    print(f'[DART SHEETS] Turnier {t["id"]} gespeichert',flush=True)


def _json(t):
    matches=[]
    for m in t['matches']:
        game=m['game']
        matches.append({'id':m['id'],'round':m['round'],'a':m['a'],'b':m['b'],
          'score':([game.sets[:] if t['sets'] else game.legs[:]][0] if game else None),
          'status':'finished' if game and game.done else 'running' if game and game.visits else 'open' if game else 'pending',
          'winner':m.get('winner')})
    return {'id':t['id'],'title':t['title'],'mode':t['mode'],'players':t['players'],
            'best_of':t['best_of'],'sets':t['sets'],'legs_per_set':t['legs_per_set'],
            'created':t['created'],'matches':matches,'standings':_table(t),
            'complete':_is_complete(t),'statistics':_statistics(t)}

def _statistics(t):
    result={name:{'name':name,'matches':0,'legs':0,'darts':0,'points':0,'first9_points':0,
      'first9_darts':0,'attempts':0,'checkouts':0,'scores_180':0,'highfinish':0,
      'lowdart':None,'specials':0} for name in t['players']}
    for item in t['matches']:
        g=item['game']
        if not g or not g.done:continue
        summary=g.summary()['players']
        for i,name in enumerate(g.names):
            z=result[name];z['matches']+=1;z['legs']+=g.legs[i]
            vv=[v for v in g.visits if v.player==i]
            z['darts']+=sum(v.darts for v in vv)
            z['points']+=sum(0 if v.bust else v.score for v in vv)
            z['attempts']+=sum(v.checkout_attempts for v in vv)
            z['checkouts']+=sum(v.checkout for v in vv)
            z['scores_180']+=sum(v.score==180 and not v.bust for v in vv)
            z['specials']+=sum(summary[i].get(k,0) for k in ('lowdarts','bullfinishes','highfinishes','highscores'))
            finishes=[v.score for v in vv if v.checkout]
            if finishes:z['highfinish']=max(z['highfinish'],*finishes)
            for leg in set(v.leg_index for v in vv):
                leg_visits=[v for v in vv if v.leg_index==leg]
                for v in leg_visits[:3]:
                    z['first9_points']+=0 if v.bust else v.score
                    z['first9_darts']+=v.darts
                if leg_visits and leg_visits[-1].checkout:
                    darts=sum(v.darts for v in leg_visits)
                    if 9<=darts<=18:z['lowdart']=min(z['lowdart'] or darts,darts)
    for z in result.values():
        z['average']=round(z['points']*3/z['darts'],2) if z['darts'] else 0
        z['first9']=round(z['first9_points']*3/z['first9_darts'],2) if z['first9_darts'] else 0
        z['checkout_percentage']=round(z['checkouts']*100/z['attempts'],2) if z['attempts'] else 0
    return list(result.values())

def _is_complete(t):
    return all((m['game'] and m['game'].done) or (m['game'] is None and m['winner']) for m in t['matches']) and (
        t['mode']!='ko' or len([m for m in t['matches'] if m['round']==max(x['round'] for x in t['matches'])])==1)

def _table(t):
    if t['mode']=='ko':return []
    tab={p:{'name':p,'played':0,'wins':0,'draws':0,'losses':0,'for':0,'against':0,'points':0} for p in t['players']}
    for item in t['matches']:
        game=item['game']
        if not game or not game.done:continue
        a,b=item['a'],item['b'];x,y=game.sets if t['sets'] else game.legs
        for player,scored,conceded in [(a,x,y),(b,y,x)]:
            z=tab[player];z['played']+=1;z['for']+=scored;z['against']+=conceded
            if scored>conceded:z['wins']+=1;z['points']+=2
            elif scored==conceded:z['draws']+=1;z['points']+=1
            else:z['losses']+=1
    return sorted(tab.values(),key=lambda x:(-x['points'],-(x['for']-x['against']),-x['for'],x['name']))

def _make_match(t,a,b,round_no):
    game=None
    if a and b:
        rules=Rules(start_score=501,mode='sets' if t['sets'] else 'legs',max_legs=t['best_of'],
                    best_of_sets=t['best_of'],best_of_legs_per_set=t['legs_per_set'],allow_draw=t['mode']!='ko' and t['best_of']%2==0)
        game=Match(rules,(a,b))
    return {'id':secrets.token_urlsafe(9),'round':round_no,'a':a,'b':b,'game':game,'winner':None,'version':0,'undo':None,'starter':None}

def _advance(t):
    if t['mode']!='ko':return
    # Create next round only after all matches of the last round have finished.
    last_round=max(m['round'] for m in t['matches'])
    batch=[m for m in t['matches'] if m['round']==last_round]
    if len(batch)==1 or not all(m['winner'] for m in batch):return
    winners=[m['winner'] for m in batch]
    for i in range(0,len(winners),2):
        t['matches'].append(_make_match(t,winners[i],winners[i+1],last_round+1))

def _get(request):
    tid=request.match_info.get('tid')
    t=TOURNAMENTS.get(tid)
    if not t:raise web.HTTPNotFound(text='Turnier nicht gefunden')
    return t

def _match(t,mid):
    item=next((m for m in t['matches'] if m['id']==mid),None)
    if not item or item['game'] is None:raise web.HTTPNotFound(text='Begegnung nicht vorhanden')
    return item

async def all_tournaments(request):
    return web.json_response({'items':[{'id':t['id'],'title':t['title'],'mode':t['mode'],'created':t['created']} for t in reversed(list(TOURNAMENTS.values()))]})

async def create(request):
    data=await request.json()
    names=data.get('players',[])
    if not isinstance(names,list) or not 2<=len(names)<=6:
        return web.json_response({'error':'Bitte 2 bis 6 Spieler angeben'},status=400)
    names=[str(n).strip()[:40] for n in names]
    if any(not n for n in names) or len(set(n.casefold() for n in names))!=len(names):
        return web.json_response({'error':'Spielernamen müssen eindeutig und ausgefüllt sein'},status=400)
    mode=data.get('mode','round1')
    if mode not in ('round1','round2','ko'):
        return web.json_response({'error':'Unbekannter Modus'},status=400)
    try:
        n=int(data.get('best_of',5)); per_set=int(data.get('legs_per_set',5))
    except (TypeError,ValueError):return web.json_response({'error':'Ungültige Best-of-Angabe'},status=400)
    if not 1<=n<=51 or not 1<=per_set<=51 or (mode=='ko' and n%2==0):
        return web.json_response({'error':'K.O. erfordert ungerades Best of X (1–51)'},status=400)
    sets=bool(data.get('sets',False))
    if sets and per_set%2==0:
        return web.json_response({'error':'Legs pro Set müssen ungerade sein'},status=400)
    t={'id':secrets.token_urlsafe(10),'title':str(data.get('title','Trainingsturnier')).strip()[:60] or 'Trainingsturnier',
       'mode':mode,'players':names,'best_of':n,'sets':sets,'legs_per_set':per_set,
       'created':datetime.now(timezone.utc).isoformat(timespec='minutes'),'matches':[]}
    if mode!='ko':
        # Circle method: every participant plays at most once per round.
        slots=names[:]
        if len(slots)%2:slots.append(None)
        count=len(slots)
        rounds=[]
        for round_no in range(1,count):
            pairs=[]
            for j in range(count//2):
                a,b=slots[j],slots[count-j-1]
                if a is not None and b is not None:
                    if (round_no+j)%2==0:a,b=b,a
                    pairs.append((a,b))
            rounds.append(pairs)
            slots=[slots[0],slots[-1],*slots[1:-1]]
        for round_index,pairs in enumerate(rounds):
            for a,b in pairs:t['matches'].append(_make_match(t,a,b,round_index+1))
        if mode=='round2':
            for round_index,pairs in enumerate(rounds):
                for a,b in pairs:t['matches'].append(_make_match(t,b,a,len(rounds)+round_index+1))
    else:
        # Distribute byes so no empty-vs-empty match exists.
        slots=1 << (len(names)-1).bit_length()
        byes=slots-len(names)
        seeded=[]
        for i,name in enumerate(names):
            seeded.append(name)
            if i<byes:seeded.append(None)
        for i in range(0,slots,2):
            a,b=seeded[i:i+2]
            m=_make_match(t,a,b,1)
            if not b:m['winner']=a
            t['matches'].append(m)
        _advance(t)
    async with LOCK:
        try:await _persist(t)
        except Exception as exc:
            print(f'[DART SHEETS] Speichern fehlgeschlagen: {exc}')
            return web.json_response({'error':'Google Sheets nicht erreichbar – Turnier nicht angelegt'},status=503)
        TOURNAMENTS[t['id']]=t
    return web.json_response(_json(t))

async def tournament(request):return web.json_response(_json(_get(request)))

async def game_state(request):
    t=_get(request);m=_match(t,request.match_info['mid']);g=m['game']
    return web.json_response({'id':m['id'],'tournament_id':t['id'],'version':m['version'],
      'kind':'x01','names':list(g.names),'remaining':g.remaining,'legs':g.legs,'sets':g.sets,
      'current':g.current,'done':g.done,'leg_number':g.leg_number,
      'rules':vars(g.rules), 'can_checkout':possible_checkout_darts(g.remaining[g.current]) if not g.done and g.remaining[g.current]<=170 else [],
      'current_stats':g.summary()['players'],'summary':g.summary() if g.done else None,
      'starter':m.get('starter'), 'last':[vars(v) for v in g.visits[-8:]],
      'can_undo':m['undo'] is not None, 'history':[vars(v) for v in g.visits[-12:]]})

async def game_throw(request):
    t=_get(request);data=await request.json()
    async with LOCK:
        m=_match(t,request.match_info['mid']);g=m['game']
        if m.get('starter') is None:return web.json_response({'error':'Vor dem Spiel bitte ausbullen'},status=409)
        if g.done:return web.json_response({'error':'Spiel beendet'},status=409)
        if data.get('version')!=m['version']:
            return web.json_response({'error':'Spielstand wurde auf anderem Gerät geändert. Bitte aktualisieren.'},status=409)
        original=copy.deepcopy(t)
        before=copy.deepcopy(g)
        try:g.submit(g.current,int(data['points']),darts=int(data.get('darts',3)),
                      checkout=bool(data.get('checkout',False)),checkout_attempts=int(data.get('checkout_attempts',0)),
                      bullfinish=bool(data.get('bullfinish',False)))
        except (ValueError,TypeError) as ex:return web.json_response({'error':str(ex)},status=400)
        m['undo']=before;m['version']+=1
        if g.done:
            a,b=g.sets if t['sets'] else g.legs
            m['winner']=m['a'] if a>b else m['b'] if b>a else None
            _advance(t)
        try:await _persist(t)
        except Exception as exc:
            TOURNAMENTS[t['id']]=original
            print(f'[DART SHEETS] Aufnahme nicht gespeichert: {exc}')
            return web.json_response({'error':'Speicherung fehlgeschlagen – Aufnahme wurde nicht gebucht'},status=503)
    return await game_state(request)

async def game_undo(request):
    t=_get(request)
    async with LOCK:
        m=_match(t,request.match_info['mid'])
        if m['undo'] is None:return web.json_response({'error':'Keine Rücknahme möglich'},status=409)
        if t['mode']=='ko' and m['game'].done and any(x['round']>m['round'] for x in t['matches']):
            return web.json_response({'error':'Folgerunde bereits angelegt'},status=409)
        original=copy.deepcopy(t)
        m['game']=m['undo'];m['undo']=None;m['winner']=None;m['version']+=1
        try:await _persist(t)
        except Exception as exc:
            TOURNAMENTS[t['id']]=original
            print(f'[DART SHEETS] Rücknahme nicht gespeichert: {exc}')
            return web.json_response({'error':'Speicherung fehlgeschlagen – Rücknahme wurde nicht übernommen'},status=503)
    return await game_state(request)


async def start_match(request):
    t=_get(request)
    data=await request.json()
    async with LOCK:
        m=_match(t,request.match_info['mid'])
        if m.get('starter') is not None:
            return await game_state(request)
        if m['game'].visits:
            return web.json_response({'error':'Match wurde bereits begonnen'},status=409)
        try: starter=int(data['starter'])
        except (KeyError,ValueError,TypeError): starter=-1
        if starter not in (0,1):return web.json_response({'error':'Ungültiger Anwurf'},status=400)
        original=copy.deepcopy(t)
        m['starter']=starter
        m['game'].current=starter
        m['game'].first_throw=starter
        try:await _persist(t)
        except Exception as exc:
            TOURNAMENTS[t['id']]=original
            print(f'[DART SHEETS] Anwurf nicht gespeichert: {exc}',flush=True)
            return web.json_response({'error':'Anwurf nicht gespeichert'},status=503)
    return await game_state(request)

async def storage_status(request):
    try:
        data=await sheet_load()
    except Exception as exc:
        print(f'[DART SHEETS] Diagnose fehlgeschlagen: {exc}',flush=True)
        return web.json_response({'ok':False,'error':str(exc),'memory_count':len(TOURNAMENTS)},status=503)
    return web.json_response({'ok':True,'sheet_count':len(data),'memory_count':len(TOURNAMENTS),
                              'ids_in_sheet':list(data),'ids_in_memory':list(TOURNAMENTS)})


def register_training_tournaments(app,auth):
    def protect(handler):
        async def wrapped(request):
            auth(request)
            return await handler(request)
        return wrapped
    app.router.add_get('/dart/api/tournaments/storage',protect(storage_status))
    app.router.add_get('/dart/api/tournaments',protect(all_tournaments))
    app.router.add_post('/dart/api/tournaments',protect(create))
    app.router.add_get('/dart/api/tournaments/{tid}',protect(tournament))
    app.router.add_get('/dart/api/tournaments/{tid}/matches/{mid}',protect(game_state))
    app.router.add_post('/dart/api/tournaments/{tid}/matches/{mid}/start',protect(start_match))
    app.router.add_post('/dart/api/tournaments/{tid}/matches/{mid}/throw',protect(game_throw))
    app.router.add_post('/dart/api/tournaments/{tid}/matches/{mid}/undo',protect(game_undo))
