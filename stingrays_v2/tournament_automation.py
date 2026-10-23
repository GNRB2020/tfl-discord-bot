"""Self-contained, idempotent training-tournament creation and advancement.
No changes to TFL or the legacy scorer. All writes in short DB transactions.
"""
import json
import logging
from uuid import UUID
from aiohttp import web
from .api import actor, body, uid, pool, response, SCHEMA, as_json
from .rules import rank_rows, round_robin, bracket_pairs
from .tournament_extensions import validate_training_rules

FORMAT={'league','groups','single_ko','double_ko'}
SCORES={170,301,501,701,1001,5001,10001}


def validate_plan(d):
    fmt=str(d.get('format','groups'))
    if fmt not in FORMAT:raise web.HTTPBadRequest(text='Unbekannter Turniermodus')
    ids=[uid(p) for p in d.get('player_ids',[])]
    if not 2<=len(ids)<=128 or len(set(ids))!=len(ids):
        raise web.HTTPBadRequest(text='2–128 unterschiedliche Teilnehmer erforderlich')
    try:n=int(d.get('group_count',2)) if fmt=='groups' else 1
    except (ValueError,TypeError):raise web.HTTPBadRequest(text='Ungültige Gruppenzahl')
    if fmt=='groups' and (n<2 or n>len(ids)//2):raise web.HTTPBadRequest(text='Pro Gruppe mindestens 2 Spieler erforderlich')
    prelim=validate_training_rules(d.get('rules') or {},elimination=fmt in ('single_ko','double_ko'))
    follow=bool(d.get('follow',False));consolation=bool(d.get('consolation',False))
    if fmt in ('single_ko','double_ko') and (follow or consolation):
        raise web.HTTPBadRequest(text='Folgerunden nach K.O.-Vorrunde derzeit nicht unterstützt')
    q=str(d.get('qualifiers','1'))
    if follow and q not in ('1','2','4','8','all'):
        raise web.HTTPBadRequest(text='Qualifizierte je Gruppe: 1,2,4,8 oder alle')
    nextfmt=str(d.get('follow_format','single_ko'))
    comfort=str(d.get('consolation_format','single_ko'))
    if follow and nextfmt not in FORMAT:raise web.HTTPBadRequest(text='Ungültiges Finalformat')
    if consolation and comfort not in FORMAT:raise web.HTTPBadRequest(text='Ungültiges Trostrundenformat')
    if consolation and not follow:raise web.HTTPBadRequest(text='Trostrunde benötigt eine Finalrunde')
    if follow and fmt=='league' and q=='1':raise web.HTTPBadRequest(text='Bei einer einzigen Liga müssen mindestens zwei Spieler in die Finalrunde einziehen')
    for key in ('follow_group_count','consolation_group_count'):
        try: value=int(d.get(key,1))
        except (ValueError,TypeError):raise web.HTTPBadRequest(text='Ungültige Gruppenanzahl in Folgerunde')
        if not 1<=value<=16:raise web.HTTPBadRequest(text='1–16 Folgegruppen zulässig')
    for key in ('follow_group_count','consolation_group_count'):
        try: value=int(d.get(key,1))
        except (ValueError,TypeError):raise web.HTTPBadRequest(text='Ungültige Gruppenanzahl in Folgerunde')
        if not 1<=value<=16:raise web.HTTPBadRequest(text='1–16 Folgegruppen zulässig')
    return {'format':fmt,'ids':ids,'group_count':n,'rules':prelim,'double_round':bool(d.get('double_round',False)),
            'follow':follow,'consolation':consolation,'qualifiers':q,'follow_format':nextfmt,'consolation_format':comfort,'follow_group_count':int(d.get('follow_group_count',1)), 'consolation_group_count':int(d.get('consolation_group_count',1))}

async def setup(req):
    a=await actor(req);d=await body(req);title=str(d.get('title','')).strip()
    if not 1<=len(title)<=150:raise web.HTTPBadRequest(text='Turniername erforderlich')
    spec=validate_plan(d)
    if a['role']=='member' and a['player_id'] not in spec['ids']:
        raise web.HTTPForbidden(text='Mitglieder können nur eigene Trainingsturniere erstellen')
    config={'auto_tournament':True,'format':spec['format'],'training_match':spec['rules'],
            'double_round':spec['double_round'],'follow':spec['follow'],'consolation':spec['consolation'],
            'qualifiers':spec['qualifiers'],'follow_format':spec['follow_format'],
            'consolation_format':spec['consolation_format'], 'follow_group_count':spec['follow_group_count'],'consolation_group_count':spec['consolation_group_count']}
    async with pool(req).acquire() as db:
      async with db.transaction():
        actual=await db.fetch('SELECT id FROM '+SCHEMA+'.players WHERE id=ANY($1::uuid[]) AND is_active IS TRUE',spec['ids'])
        if len(actual)!=len(spec['ids']):raise web.HTTPBadRequest(text='Ungültiger oder inaktiver Spieler')
        cid=await db.fetchval(f'''INSERT INTO {SCHEMA}.competitions(title,kind,status,rules,created_by)
            VALUES($1,'training_tournament','active',$2::jsonb,$3) RETURNING id''',title,json.dumps(config),a['id'])
        for pid in spec['ids']:
            await db.execute(f'INSERT INTO {SCHEMA}.entries(competition_id,player_id) VALUES($1,$2)',cid,pid)
        kind='groups' if spec['format']=='groups' else 'league' if spec['format']=='league' else 'knockout'
        phase=await db.fetchval(f'''INSERT INTO {SCHEMA}.phases(competition_id,name,kind,phase_order,status,rules)
            VALUES($1,'Vorrunde',$2,1,'open',$3::jsonb) RETURNING id''',cid,kind,json.dumps({'stage':'preliminary','format':spec['format'],'participants':[str(x) for x in spec['ids']],'match_rules':spec['rules']}))
        created=0
        if kind in ('groups','league'):
            buckets=[[] for _ in range(spec['group_count'])]
            for i,pid in enumerate(spec['ids']):
                j=i%len(buckets) if (i//len(buckets))%2==0 else len(buckets)-1-i%len(buckets)
                buckets[j].append(pid)
            for ix,people in enumerate(buckets):
                gid=await db.fetchval(f'''INSERT INTO {SCHEMA}.groups(phase_id,name,sort_order)
                    VALUES($1,$2,$3) RETURNING id''',phase,'Gruppe '+chr(65+ix) if kind=='groups' else 'Liga',ix+1)
                for pid in people:
                    await db.execute(f'''INSERT INTO {SCHEMA}.group_members(group_id,entry_id)
                        SELECT $1,id FROM {SCHEMA}.entries WHERE competition_id=$2 AND player_id=$3''',gid,cid,pid)
                for rnd,p1,p2 in round_robin(people,spec['double_round']):
                    await db.execute(f'''INSERT INTO {SCHEMA}.matches(competition_id,phase_id,group_id,round_number,player1_id,player2_id,rules)
                        VALUES($1,$2,$3,$4,$5,$6,$7::jsonb)''',cid,phase,gid,rnd,p1,p2,json.dumps(spec['rules']))
                    created+=1
        else:
            pairs=bracket_pairs(spec['ids'])
            byes=[p for x,y in pairs if not(x and y) for p in (x,y) if p]
            await db.execute(f'UPDATE {SCHEMA}.phases SET rules=rules || $2::jsonb WHERE id=$1',phase,json.dumps({'bye_players':[str(p) for p in byes]}))
            for i,(p1,p2) in enumerate(pairs):
                if p1 is None or p2 is None:continue
                await db.execute(f'''INSERT INTO {SCHEMA}.matches(competition_id,phase_id,round_number,bracket_position,player1_id,player2_id,rules)
                  VALUES($1,$2,1,$3,$4,$5,$6::jsonb)''',cid,phase,i+1,p1,p2,json.dumps(spec['rules']))
                created+=1
        if not created:raise web.HTTPBadRequest(text='Keine Begegnungen erzeugt')
    return response({'id':cid,'created':created,'groups':spec['group_count'],'automatic':True},201)


def winner(m):
    s1,s2=(m['sets1'],m['sets2']) if (m['sets1'] or m['sets2']) else (m['legs1'],m['legs2'])
    if s1 is None or s2 is None or s1==s2:return None
    return m['player1_id'] if s1>s2 else m['player2_id']

async def _make_stage(db,cid,stage,ids,fmt,match_rules,ngroups=1,double_round=False):
    if fmt in ('single_ko','double_ko'):
        match_rules={**match_rules,'allow_draw':False}
        if match_rules['mode']=='legs' and match_rules['max_legs']%2==0:
            match_rules['max_legs']+=1
    order=2 if stage=='final' else 3
    ph=await db.fetchval(f'''INSERT INTO {SCHEMA}.phases(competition_id,name,kind,phase_order,status,rules)
      VALUES($1,$2,$3,$4,'open',$5::jsonb) RETURNING id''',cid,'Finalrunde' if stage=='final' else 'Trostrunde',
      'groups' if fmt in ('groups','league') else 'knockout',order,
      json.dumps({'stage':stage,'format':fmt,'participants':[str(p) for p in ids],'match_rules':match_rules}))
    count=0
    if fmt in ('groups','league'):
        buckets=[[] for _ in range(max(1,min(ngroups,len(ids)//2)))]
        for i,pid in enumerate(ids):buckets[i%len(buckets)].append(pid)
        for i,people in enumerate(buckets):
            gid=await db.fetchval(f'''INSERT INTO {SCHEMA}.groups(phase_id,name,sort_order) VALUES($1,$2,$3) RETURNING id''',ph,'Gruppe '+str(i+1),i+1)
            for pid in people:await db.execute(f'''INSERT INTO {SCHEMA}.group_members(group_id,entry_id)
                SELECT $1,id FROM {SCHEMA}.entries WHERE competition_id=$2 AND player_id=$3''',gid,cid,pid)
            for rnd,p1,p2 in round_robin(people,double_round):
                await db.execute(f'''INSERT INTO {SCHEMA}.matches(competition_id,phase_id,group_id,round_number,player1_id,player2_id,rules)
                  VALUES($1,$2,$3,$4,$5,$6,$7::jsonb)''',cid,ph,gid,rnd,p1,p2,json.dumps(match_rules));count+=1
    else:
        if match_rules['mode']=='legs' and match_rules['max_legs']%2==0:
            match_rules={**match_rules,'max_legs':match_rules['max_legs']+1,'allow_draw':False}
        pairs=bracket_pairs(ids)
        byes=[p for x,y in pairs if not(x and y) for p in (x,y) if p]
        await db.execute(f'UPDATE {SCHEMA}.phases SET rules=rules || $2::jsonb WHERE id=$1',ph,json.dumps({'bye_players':[str(p) for p in byes]}))
        for i,(p1,p2) in enumerate(pairs):
            if p1 is None or p2 is None:continue
            await db.execute(f'''INSERT INTO {SCHEMA}.matches(competition_id,phase_id,round_number,bracket_position,player1_id,player2_id,rules)
             VALUES($1,$2,1,$3,$4,$5,$6::jsonb)''',cid,ph,i+1,p1,p2,json.dumps(match_rules));count+=1
    return count

async def progress(req,cid):
    """Run after score commit, serialize by competition row. Idempotent across tablets."""
    async with pool(req).acquire() as db:
      async with db.transaction():
        c=await db.fetchrow(f'''SELECT id,rules,status FROM {SCHEMA}.competitions
          WHERE id=$1 AND kind='training_tournament' AND deleted_at IS NULL FOR UPDATE''',cid)
        if not c or c['status'] not in ('active','draft'):return
        cfg=as_json(c['rules']);
        if not cfg.get('auto_tournament'):return
        phases=await db.fetch(f'SELECT id,phase_order,kind,rules,status FROM {SCHEMA}.phases WHERE competition_id=$1 ORDER BY phase_order',cid)
        if not phases:return
        pre=phases[0]
        pending=await db.fetchval(f"SELECT count(*) FROM {SCHEMA}.matches WHERE phase_id=$1 AND status<>'finished'",pre['id'])
        total=await db.fetchval(f'SELECT count(*) FROM {SCHEMA}.matches WHERE phase_id=$1',pre['id'])
        if not pending and total and not any(p['phase_order']>1 for p in phases):
            if cfg['format'] in ('league','groups'):
                await db.execute(f"UPDATE {SCHEMA}.phases SET status='closed',closed_at=now() WHERE id=$1 AND status<>'closed'",pre['id'])
            if cfg.get('follow'):
                groups=await db.fetch(f'SELECT id FROM {SCHEMA}.groups WHERE phase_id=$1 ORDER BY sort_order',pre['id'])
                q=cfg.get('qualifiers','1');n=99999 if q=='all' else int(q)
                selected=[];rest=[]
                for g in groups:
                    members=await db.fetch(f'''SELECT e.player_id FROM {SCHEMA}.group_members gm
                     JOIN {SCHEMA}.entries e ON e.id=gm.entry_id WHERE gm.group_id=$1''',g['id'])
                    ms=await db.fetch(f'''SELECT player1_id,player2_id,status,legs1,legs2,sets1,sets2 FROM {SCHEMA}.matches
                      WHERE group_id=$1''',g['id'])
                    ranks=rank_rows([dict(m) for m in ms],[p['player_id'] for p in members]);selected.extend(p['player_id'] for p in ranks[:n]);rest.extend(p['player_id'] for p in ranks[n:])
                if len(selected)<2:raise web.HTTPConflict(text='Weniger als zwei qualifizierte Spieler')
                await _make_stage(db,cid,'final',selected,cfg.get('follow_format','single_ko'),cfg['training_match'],cfg.get('follow_group_count',1))
                if cfg.get('consolation') and len(rest)>=2:
                    await _make_stage(db,cid,'consolation',rest,cfg.get('consolation_format','single_ko'),cfg['training_match'],cfg.get('consolation_group_count',1))
            elif cfg['format'] in ('league','groups'):
                await db.execute(f"UPDATE {SCHEMA}.competitions SET status='finished' WHERE id=$1",cid)
        # advance every KO phase, including preliminary single/double elimination
        phases=await db.fetch(f'SELECT id,phase_order,kind,rules,status FROM {SCHEMA}.phases WHERE competition_id=$1 ORDER BY phase_order',cid)
        for ph in phases:
            pr=as_json(ph['rules']);fmt=pr.get('format')
            if fmt not in ('single_ko','double_ko') or ph['status']=='closed':continue
            mx=await db.fetchval(f'SELECT max(round_number) FROM {SCHEMA}.matches WHERE phase_id=$1',ph['id'])
            if mx is None:continue
            rows=await db.fetch(f'SELECT * FROM {SCHEMA}.matches WHERE phase_id=$1 AND round_number=$2 ORDER BY bracket_position',ph['id'],mx)
            if not rows or any(m['status']!='finished' for m in rows):continue
            allrows=await db.fetch(f'SELECT * FROM {SCHEMA}.matches WHERE phase_id=$1 ORDER BY round_number,bracket_position',ph['id'])
            participants=[UUID(p) for p in pr.get('participants',[])]
            if fmt=='single_ko':
                remaining=[winner(m) for m in rows]
                if mx==1:remaining+= [UUID(x) for x in pr.get('bye_players',[])]
            else:
                loss={p:0 for p in participants}
                for m in allrows:
                    w=winner(m)
                    if w is None:return
                    l=m['player2_id'] if w==m['player1_id'] else m['player1_id'];loss[l]=loss.get(l,0)+1
                remaining=[p for p in participants if loss.get(p,0)<2]
            remaining=[p for p in remaining if p is not None]
            if len(remaining)<=1:
                await db.execute(f"UPDATE {SCHEMA}.phases SET status='closed',closed_at=now() WHERE id=$1",ph['id']);continue
            rules=pr.get('match_rules',cfg['training_match']);next_pairs=[(x,y) for x,y in bracket_pairs(remaining) if x and y]
            if not next_pairs:continue
            for i,(p1,p2) in enumerate(next_pairs):
                await db.execute(f'''INSERT INTO {SCHEMA}.matches(competition_id,phase_id,round_number,bracket_position,player1_id,player2_id,rules)
                VALUES($1,$2,$3,$4,$5,$6,$7::jsonb)''',cid,ph['id'],mx+1,i+1,p1,p2,json.dumps(rules))
        # Close once all phases end; group follow-on phases finish when all games finish.
        phase_rows=await db.fetch(f'SELECT id,kind,status FROM {SCHEMA}.phases WHERE competition_id=$1',cid)
        for ph in phase_rows:
            if ph['status']=='closed' or ph['kind']=='knockout':continue
            nonfinal=await db.fetchval(f"SELECT count(*) FROM {SCHEMA}.matches WHERE phase_id=$1 AND status<>'finished'",ph['id'])
            anygames=await db.fetchval(f'SELECT count(*) FROM {SCHEMA}.matches WHERE phase_id=$1',ph['id'])
            if anygames and not nonfinal:await db.execute(f"UPDATE {SCHEMA}.phases SET status='closed',closed_at=now() WHERE id=$1",ph['id'])
        active=await db.fetchval(f"SELECT count(*) FROM {SCHEMA}.phases WHERE competition_id=$1 AND status<>'closed'",cid)
        if active==0:await db.execute(f"UPDATE {SCHEMA}.competitions SET status='finished' WHERE id=$1",cid)

async def live_games(req):
    await actor(req)
    async with pool(req).acquire() as db:
        rows=await db.fetch(f'''SELECT m.id,m.competition_id,c.title,c.kind,p1.display_name AS player1,p2.display_name AS player2,
           m.legs1,m.legs2,m.sets1,m.sets2,m.state,m.started_at FROM {SCHEMA}.matches m
           JOIN {SCHEMA}.competitions c ON c.id=m.competition_id AND c.deleted_at IS NULL
           JOIN {SCHEMA}.players p1 ON p1.id=m.player1_id JOIN {SCHEMA}.players p2 ON p2.id=m.player2_id
           WHERE m.status='running' ORDER BY m.started_at DESC LIMIT 16''')
    out=[]
    for r in rows:
        state=as_json(r['state'])
        totals=[[0,0],[0,0]]
        for visit in state.get('visits',[]):
            idx=visit.get('player')
            if idx not in (0,1):continue
            totals[idx][0]+=int(visit.get('score',0) or 0)
            totals[idx][1]+=int(visit.get('darts',3) or 3)
        averages=[round(3*points/darts,2) if darts else None for points,darts in totals]
        out.append({'id':r['id'],'competition_id':r['competition_id'],'title':r['title'],
          'kind':r['kind'],'player1':r['player1'],'player2':r['player2'],
          'legs':state.get('legs',[r['legs1'] or 0,r['legs2'] or 0]),'sets':state.get('sets',[r['sets1'] or 0,r['sets2'] or 0]),
          'remaining':state.get('remaining',[]),'averages':averages,'started_at':r['started_at']})
    return response(out)

async def report(req):
    await actor(req);cid=uid(req.match_info['cid'])
    async with pool(req).acquire() as db:
        c=await db.fetchrow(f'SELECT title,kind,status FROM {SCHEMA}.competitions WHERE id=$1',cid)
        if not c or c['kind']!='training_tournament':raise web.HTTPNotFound()
        matches=await db.fetch(f'''SELECT m.*,ph.phase_order FROM {SCHEMA}.matches m JOIN {SCHEMA}.phases ph ON ph.id=m.phase_id
          WHERE m.competition_id=$1 AND m.status='finished' ORDER BY ph.phase_order DESC,m.round_number DESC''',cid)
        players=await db.fetch(f'''SELECT p.id,p.display_name FROM {SCHEMA}.entries e JOIN {SCHEMA}.players p ON p.id=e.player_id
          WHERE e.competition_id=$1''',cid)
    score={p['id']:{'player_id':p['id'],'name':p['display_name'],'wins':0,'losses':0,'points':0,'darts':0,'rank_score':0} for p in players}
    for m in matches:
        w=winner(m)
        for idx,p in enumerate((m['player1_id'],m['player2_id'])):
            if p not in score:continue
            d=score[p];d['wins']+=int(w==p);d['losses']+=int(w is not None and w!=p)
            state=as_json(m['state'])
            for v in state.get('visits',[]):
                if v.get('player')==idx:
                    d['points']+=int(v.get('score',0));d['darts']+=int(v.get('darts',3))
            if w==p:d['rank_score']+=1000*int(m['phase_order'] or 1)+int(m['round_number'] or 1)
    results=sorted(score.values(),key=lambda r:(-r['rank_score'],-r['wins'],r['losses'],r['name']))
    for i,r in enumerate(results,1):r['place']=i;r['average']=round(3*r['points']/r['darts'],2) if r['darts'] else None
    return response({'title':c['title'],'finished':c['status']=='finished','placements':results,'provisional':True})
