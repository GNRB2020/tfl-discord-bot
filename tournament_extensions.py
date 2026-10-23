"""Training tournament group -> final/consolation workflows, no TFL or legacy mutation.

Every write is authorized through the originating competition, and game results are
never silently replaced. This module is imported by the V2 router only.
"""
from __future__ import annotations
import json
from uuid import UUID
from aiohttp import web
from .rules import rank_rows, round_robin, bracket_pairs, mode_rules
from .api import SCHEMA, actor, body, uid, pool, response, require_manager, as_json

START_SCORES={170,301,501,701,1001,5001,10001}
FORMATS={'single_ko','double_ko','placement','groups'}
STAGES={'final','consolation'}


def validate_training_rules(payload, *, elimination=False):
    if not isinstance(payload,dict):raise web.HTTPBadRequest(text='Spielregeln müssen ein Objekt sein')
    try:
        start=int(payload.get('start_score',501))
        mode=str(payload.get('mode','legs'))
        max_legs=int(payload.get('max_legs',5))
        best_sets=int(payload.get('best_of_sets',3))
        legs_per_set=int(payload.get('best_of_legs_per_set',3))
    except (ValueError,TypeError):raise web.HTTPBadRequest(text='Ungültige Spielregeln')
    if start not in START_SCORES:raise web.HTTPBadRequest(text='Startscore muss 170, 301, 501, 701, 1001, 5001 oder 10001 sein')
    if mode not in ('legs','sets') or not 1<=max_legs<=101 or not 1<=best_sets<=21 or not 1<=legs_per_set<=21:
        raise web.HTTPBadRequest(text='Ungültige Spielart oder Matchlänge')
    if mode=='sets' and (best_sets%2==0 or legs_per_set%2==0):
        raise web.HTTPBadRequest(text='Best of Sets und Best of Legs je Set müssen ungerade sein')
    if elimination and mode=='legs' and max_legs%2==0:
        raise web.HTTPBadRequest(text='K.O.-Spiele benötigen ungerade Best-of-Legs-Werte')
    return {'start_score':start,'mode':mode,'max_legs':max_legs,
            'best_of_sets':best_sets,'best_of_legs_per_set':legs_per_set,
            'allow_draw':bool(mode=='legs' and max_legs%2==0 and not elimination),'double_out':True}


async def update_training_rules(req):
    a=await actor(req);d=await body(req);cid=uid(req.match_info['cid']);settings=validate_training_rules(d.get('rules') or d)
    async with pool(req).acquire() as db:
      async with db.transaction():
        c=await db.fetchrow(f'SELECT id,kind,rules FROM {SCHEMA}.competitions WHERE id=$1 AND deleted_at IS NULL FOR UPDATE',cid)
        if not c or c['kind']!='training_tournament':raise web.HTTPBadRequest(text='Nur für Trainingsturniere')
        await require_manager(db,a,cid)
        config=as_json(c['rules']);config['training_match']=settings
        await db.execute(f'UPDATE {SCHEMA}.competitions SET rules=$2::jsonb WHERE id=$1',cid,json.dumps(config))
        count=await db.fetchval(f'''SELECT count(*) FROM {SCHEMA}.matches m JOIN {SCHEMA}.phases ph ON ph.id=m.phase_id
            WHERE m.competition_id=$1 AND m.status='open' AND ph.phase_order=1''',cid)
        await db.execute(f'''UPDATE {SCHEMA}.matches m SET rules=$2::jsonb FROM {SCHEMA}.phases ph
            WHERE m.phase_id=ph.id AND m.competition_id=$1 AND m.status='open' AND ph.phase_order=1''',cid,json.dumps(settings))
    return response({'saved':True,'updated_unstarted_matches':count,'rules':settings})


async def _preliminary(db,cid):
    c=await db.fetchrow(f'SELECT id,kind,rules FROM {SCHEMA}.competitions WHERE id=$1 AND deleted_at IS NULL',cid)
    if not c or c['kind']!='training_tournament':raise web.HTTPBadRequest(text='Kein Trainingsturnier')
    ph=await db.fetchrow(f'''SELECT id FROM {SCHEMA}.phases WHERE competition_id=$1 AND kind='groups'
        AND phase_order=1 LIMIT 1''',cid)
    if not ph:raise web.HTTPConflict(text='Vorrunde nicht angelegt')
    groups=await db.fetch(f'''SELECT id,name FROM {SCHEMA}.groups WHERE phase_id=$1 ORDER BY sort_order,id''',ph['id'])
    ranks=[];complete=True
    for group in groups:
        people=await db.fetch(f'''SELECT e.player_id,p.display_name FROM {SCHEMA}.group_members gm
           JOIN {SCHEMA}.entries e ON e.id=gm.entry_id JOIN {SCHEMA}.players p ON p.id=e.player_id
           WHERE gm.group_id=$1''',group['id'])
        matches=await db.fetch(f'''SELECT player1_id,player2_id,status,legs1,legs2,sets1,sets2 FROM {SCHEMA}.matches
           WHERE group_id=$1 ORDER BY created_at''',group['id'])
        if len(people)>1 and (not matches or any(m['status']!='finished' for m in matches)):complete=False
        ranked=rank_rows([dict(m) for m in matches],[x['player_id'] for x in people]);named={r['player_id']:r['display_name'] for r in people}
        ranks.append({'group_id':group['id'],'name':group['name'],'rows':[{**r,'display_name':named.get(r['player_id'],'?')} for r in ranked],
                      'finished':sum(m['status']=='finished' for m in matches),'total':len(matches)})
    return c,ranks,complete


def choose(ranks,count,stage):
    if count=='all':n=99999
    else:
        try:n=int(count)
        except (ValueError,TypeError):raise web.HTTPBadRequest(text='Ungültige Zahl an Qualifizierten')
        if n not in (1,2,4,8):raise web.HTTPBadRequest(text='Erlaubt: 1, 2, 4, 8 oder Alle pro Gruppe')
    chosen=[]
    for g in ranks:
        rows=g['rows'];subset=rows[:n] if stage=='final' else rows[n:]
        chosen.extend(r['player_id'] for r in subset)
    return chosen


async def stage_preview(req):
    await actor(req);cid=uid(req.match_info['cid'])
    async with pool(req).acquire() as db:
        _,ranks,complete=await _preliminary(db,cid)
    return response({'groups':ranks,'preliminary_complete':complete})


def matchup(pairs):
    return [(p1,p2) for p1,p2 in pairs if p1 is not None and p2 is not None]


async def create_training_stage(req):
    a=await actor(req);d=await body(req);cid=uid(req.match_info['cid']);stage=str(d.get('stage',''))
    fmt=str(d.get('format','single_ko'));count=str(d.get('qualifiers','2'))
    if stage not in STAGES or fmt not in FORMATS:raise web.HTTPBadRequest(text='Unbekannte Folgerunde')
    if count not in ('1','2','4','8','all'):raise web.HTTPBadRequest(text='Qualifizierte pro Gruppe: 1,2,4,8 oder Alle')
    override=d.get('player_ids',None)
    if override is not None and (not isinstance(override,list) or len(override)>128):raise web.HTTPBadRequest(text='Ungültige manuelle Setzliste')
    try:ngroups=int(d.get('group_count',1))
    except (ValueError,TypeError):raise web.HTTPBadRequest(text='Ungültige Gruppenanzahl')
    if not 1<=ngroups<=16:raise web.HTTPBadRequest(text='Maximal 16 Folgegruppen')
    if fmt=='placement' and count!='all':raise web.HTTPBadRequest(text='Platzierungsspiele benötigen die Auswahl Alle')
    async with pool(req).acquire() as db:
      async with db.transaction():
        c,ranks,complete=await _preliminary(db,cid)
        await require_manager(db,a,cid)
        if override is None and not complete:raise web.HTTPConflict(text='Vorrunde noch nicht abgeschlossen. Für eine vorzeitige Folgerunde Spieler manuell auswählen.')
        entrants=[uid(x) for x in override] if override is not None else choose(ranks,count,stage)
        if len(entrants)!=len(set(entrants)) or len(entrants)<2:raise web.HTTPBadRequest(text='Mindestens zwei unterschiedliche Spieler erforderlich')
        valid={r['player_id'] for r in await db.fetch(f'SELECT player_id FROM {SCHEMA}.entries WHERE competition_id=$1',cid)}
        if any(x not in valid for x in entrants):raise web.HTTPBadRequest(text='Spieler gehört nicht zum Turnier')
        other='consolation' if stage=='final' else 'final'
        phases=await db.fetch(f'''SELECT id,rules FROM {SCHEMA}.phases WHERE competition_id=$1 AND phase_order>1 FOR UPDATE''',cid)
        this=next((p for p in phases if as_json(p['rules']).get('stage')==stage),None)
        other_phase=next((p for p in phases if as_json(p['rules']).get('stage')==other),None)
        if other_phase and set(entrants)&{uid(x) for x in as_json(other_phase['rules']).get('participants',[])}:
            raise web.HTTPConflict(text='Spieler bereits der anderen Folgerunde zugeordnet')
        if this:
            played=await db.fetchval(f"SELECT EXISTS(SELECT 1 FROM {SCHEMA}.matches WHERE phase_id=$1 AND status<>'open')",this['id'])
            if played:raise web.HTTPConflict(text='Folgerunde enthält gestartete/gewertete Spiele und kann nicht neu erstellt werden')
            await db.execute(f'DELETE FROM {SCHEMA}.matches WHERE phase_id=$1',this['id'])
            await db.execute(f'DELETE FROM {SCHEMA}.group_members WHERE group_id IN (SELECT id FROM {SCHEMA}.groups WHERE phase_id=$1)',this['id'])
            await db.execute(f'DELETE FROM {SCHEMA}.groups WHERE phase_id=$1',this['id'])
        preliminary=as_json(c['rules']).get('training_match',{})
        overrides=d.get('rules') or preliminary
        rules=validate_training_rules(overrides,elimination=fmt in ('single_ko','double_ko','placement'))
        p_rules={'stage':stage,'format':fmt,'qualifiers':count,'participants':[str(p) for p in entrants],
                 'manual':override is not None,'match_rules':rules}
        if this:
            phase_id=this['id']
            await db.execute(f'''UPDATE {SCHEMA}.phases SET kind=$2,name=$3,rules=$4::jsonb,status='open'
                WHERE id=$1''',phase_id,'groups' if fmt=='groups' else 'knockout',
                'Finalrunde' if stage=='final' else 'Trostrunde',json.dumps(p_rules))
        else:
            phase_id=await db.fetchval(f'''INSERT INTO {SCHEMA}.phases(competition_id,name,kind,phase_order,status,rules)
                  VALUES($1,$2,$3,(SELECT COALESCE(MAX(phase_order),0)+1 FROM {SCHEMA}.phases WHERE competition_id=$1),'open',$4::jsonb)
                  RETURNING id''',cid,'Finalrunde' if stage=='final' else 'Trostrunde',
                  'groups' if fmt=='groups' else 'knockout',json.dumps(p_rules))
        created=0
        if fmt=='groups':
            ngroups=min(ngroups,len(entrants)//2)
            if ngroups<1:ngroups=1
            buckets=[[] for i in range(ngroups)]
            for i,pid in enumerate(entrants):
                k=i%ngroups if (i//ngroups)%2==0 else ngroups-1-(i%ngroups)
                buckets[k].append(pid)
            for idx,bucket in enumerate(buckets):
                gid=await db.fetchval(f'''INSERT INTO {SCHEMA}.groups(phase_id,name,sort_order)
                     VALUES($1,$2,$3) RETURNING id''',phase_id,('Finalgruppe ' if stage=='final' else 'Trostgruppe ')+str(idx+1),idx+1)
                for pid in bucket:
                    await db.execute(f'''INSERT INTO {SCHEMA}.group_members(group_id,entry_id)
                       SELECT $1,id FROM {SCHEMA}.entries WHERE competition_id=$2 AND player_id=$3''',gid,cid,pid)
                for rnd,p1,p2 in round_robin(bucket,bool(d.get('double_round',False))):
                    await db.execute(f'''INSERT INTO {SCHEMA}.matches(competition_id,phase_id,group_id,round_number,player1_id,player2_id,rules)
                        VALUES($1,$2,$3,$4,$5,$6,$7::jsonb)''',cid,phase_id,gid,rnd,p1,p2,json.dumps(rules));created+=1
        else:
            pairs=[]
            if fmt=='placement':
                if len(ranks)<2:raise web.HTTPBadRequest(text='Platzierungsspiele benötigen mindestens zwei Vorrundengruppen')
                allowed=set(entrants)
                for i in range(0,len(ranks)-1,2):
                    for pa,pb in zip(ranks[i]['rows'],ranks[i+1]['rows']):
                        if pa['player_id'] in allowed and pb['player_id'] in allowed:
                            pairs.append((pa['player_id'],pb['player_id']))
                if not pairs:raise web.HTTPBadRequest(text='Keine entsprechenden Platzierungspaarungen vorhanden')
            else:pairs=matchup(bracket_pairs(entrants))
            for idx,(p1,p2) in enumerate(pairs):
                await db.execute(f'''INSERT INTO {SCHEMA}.matches(competition_id,phase_id,round_number,bracket_position,player1_id,player2_id,rules)
                  VALUES($1,$2,1,$3,$4,$5,$6::jsonb)''',cid,phase_id,idx+1,p1,p2,json.dumps(rules));created+=1
    return response({'phase_id':phase_id,'created':created,'participants':len(entrants),'format':fmt},201)


async def advance_training_or_original(req):
    from .api import advance_knockout
    pid=uid(req.match_info['pid'])
    async with pool(req).acquire() as db:
        row=await db.fetchrow(f'SELECT rules FROM {SCHEMA}.phases WHERE id=$1',pid)
    cfg=as_json(row['rules']) if row else {}
    if cfg.get('stage') not in STAGES or cfg.get('format') not in ('single_ko','double_ko'):
        return await advance_knockout(req)
    a=await actor(req);await body(req)
    cid=None
    async with pool(req).acquire() as db:
      async with db.transaction():
        p=await db.fetchrow(f'SELECT * FROM {SCHEMA}.phases WHERE id=$1 FOR UPDATE',pid)
        if not p:raise web.HTTPNotFound()
        cid=p['competition_id'];await require_manager(db,a,cid)
        rules=as_json(p['rules']);participants=[uid(x) for x in rules.get('participants',[])]
        matches=await db.fetch(f'''SELECT * FROM {SCHEMA}.matches WHERE phase_id=$1 ORDER BY round_number,bracket_position FOR UPDATE''',pid)
        if not matches or any(m['status']!='finished' for m in matches):raise web.HTTPConflict(text='Erst alle Begegnungen abschließen')
        mx=max(m['round_number'] or 1 for m in matches)
        seen_round={m['round_number'] for m in matches}
        if len(seen_round)<1:raise web.HTTPConflict(text='Keine gespielte Runde')
        losses={k:0 for k in participants}
        for m in matches:
            a1,a2=(m['sets1'],m['sets2']) if m['sets1'] or m['sets2'] else (m['legs1'],m['legs2'])
            if a1 is None or a2 is None or a1==a2:raise web.HTTPConflict(text='K.O.-Begegnung hat kein eindeutiges Ergebnis')
            loser=m['player1_id'] if a1<a2 else m['player2_id']
            losses[loser]+=1
        fmt=rules['format'];limit=1 if fmt=='single_ko' else 2
        alive=[k for k in participants if losses[k]<limit]
        if len(alive)==1:
            await db.execute(f"UPDATE {SCHEMA}.phases SET status='closed',closed_at=now() WHERE id=$1",pid)
            return response({'completed':True,'winner_id':alive[0],'created':0})
        if len(alive)<2:raise web.HTTPConflict(text='Keine qualifizierten Spieler mehr')
        pairs=[]
        if fmt=='single_ko' or len(alive)==2:
            pairs=matchup(bracket_pairs(alive))
        else:
            for count in (0,1):
                pool_ids=[p for p in alive if losses[p]==count]
                pairs.extend(matchup(bracket_pairs(pool_ids)))
        if not pairs:raise web.HTTPConflict(text='Keine neue Begegnung möglich')
        for j,(p1,p2) in enumerate(pairs):
            await db.execute(f'''INSERT INTO {SCHEMA}.matches(competition_id,phase_id,round_number,bracket_position,player1_id,player2_id,rules)
             VALUES($1,$2,$3,$4,$5,$6,$7::jsonb)''',cid,pid,mx+1,j+1,p1,p2,json.dumps(rules['match_rules']))
    return response({'created':len(pairs),'round':mx+1,'format':fmt})


async def edit_stage_pairing(req):
    a=await actor(req);d=await body(req);mid=uid(req.match_info['mid']);first=uid(d.get('player1_id'));second=uid(d.get('player2_id'))
    if first==second:raise web.HTTPBadRequest(text='Zwei unterschiedliche Spieler wählen')
    async with pool(req).acquire() as db:
      async with db.transaction():
        m=await db.fetchrow(f'SELECT * FROM {SCHEMA}.matches WHERE id=$1 FOR UPDATE',mid)
        if not m:raise web.HTTPNotFound()
        await require_manager(db,a,m['competition_id'])
        if m['status']!='open':raise web.HTTPConflict(text='Nur noch nicht gestartete Begegnungen bearbeiten')
        p=await db.fetchrow(f'SELECT rules FROM {SCHEMA}.phases WHERE id=$1',m['phase_id'])
        cfg=as_json(p['rules']) if p else {}
        if cfg.get('stage') not in STAGES:raise web.HTTPForbidden(text='Nur Final-/Trostrunden-Begegnungen')
        valid={uid(v) for v in cfg.get('participants',[])}
        if first not in valid or second not in valid:raise web.HTTPBadRequest(text='Spieler ist nicht für diese Runde gesetzt')
        for pid in (first,second):
            collision=await db.fetchval(f'''SELECT EXISTS(SELECT 1 FROM {SCHEMA}.matches
               WHERE phase_id=$1 AND round_number=$2 AND id<>$3 AND (player1_id=$4 OR player2_id=$4))''',m['phase_id'],m['round_number'],mid,pid)
            if collision:raise web.HTTPConflict(text='Spieler hat in dieser Runde bereits eine andere Begegnung')
        await db.execute(f'''UPDATE {SCHEMA}.matches SET player1_id=$2,player2_id=$3,state='{{}}'::jsonb,
            state_version=0 WHERE id=$1''',mid,first,second)
    return response({'updated':True})


async def add_stage_pairing(req):
    a=await actor(req);d=await body(req);pid=uid(req.match_info['pid']);p1=uid(d.get('player1_id'));p2=uid(d.get('player2_id'))
    if p1==p2:raise web.HTTPBadRequest(text='Verschiedene Spieler erforderlich')
    async with pool(req).acquire() as db:
      async with db.transaction():
        ph=await db.fetchrow(f'SELECT * FROM {SCHEMA}.phases WHERE id=$1 FOR UPDATE',pid)
        if not ph:raise web.HTTPNotFound()
        await require_manager(db,a,ph['competition_id'])
        cfg=as_json(ph['rules']);allowed={uid(p) for p in cfg.get('participants',[])}
        if cfg.get('stage') not in STAGES or p1 not in allowed or p2 not in allowed:raise web.HTTPBadRequest(text='Ungültige Folgerundenbegegnung')
        try:round_no=int(d.get('round_number',1))
        except (TypeError,ValueError):raise web.HTTPBadRequest(text='Ungültige Rundennummer')
        if not 1<=round_no<=128:raise web.HTTPBadRequest(text='Ungültige Rundennummer')
        for player in (p1,p2):
            present=await db.fetchval(f'''SELECT EXISTS(SELECT 1 FROM {SCHEMA}.matches WHERE phase_id=$1 AND round_number=$2
                AND (player1_id=$3 OR player2_id=$3))''',pid,round_no,player)
            if present:raise web.HTTPConflict(text='Spieler bereits in dieser Runde eingeteilt')
        pos=await db.fetchval(f'SELECT COALESCE(MAX(bracket_position),0)+1 FROM {SCHEMA}.matches WHERE phase_id=$1 AND round_number=$2',pid,round_no)
        mid=await db.fetchval(f'''INSERT INTO {SCHEMA}.matches(competition_id,phase_id,round_number,bracket_position,player1_id,player2_id,rules)
         VALUES($1,$2,$3,$4,$5,$6,$7::jsonb) RETURNING id''',ph['competition_id'],pid,round_no,pos,p1,p2,json.dumps(cfg['match_rules']))
    return response({'id':mid},201)


async def remove_stage_pairing(req):
    a=await actor(req);await body(req);mid=uid(req.match_info['mid'])
    async with pool(req).acquire() as db:
      async with db.transaction():
        m=await db.fetchrow(f'SELECT * FROM {SCHEMA}.matches WHERE id=$1 FOR UPDATE',mid)
        if not m:raise web.HTTPNotFound()
        await require_manager(db,a,m['competition_id'])
        ph=await db.fetchrow(f'SELECT rules FROM {SCHEMA}.phases WHERE id=$1',m['phase_id'])
        if as_json(ph['rules']).get('stage') not in STAGES or m['status']!='open':raise web.HTTPConflict(text='Nur ungespielte Folgerundenbegegnungen löschbar')
        await db.execute(f'DELETE FROM {SCHEMA}.matches WHERE id=$1',mid)
    return response({'removed':True})
