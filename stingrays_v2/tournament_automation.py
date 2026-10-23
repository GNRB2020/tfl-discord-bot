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
    try: extra_thirds=int(d.get('best_third_count',0))
    except (ValueError,TypeError):raise web.HTTPBadRequest(text='Ungültige Anzahl bester Dritter')
    if not 0<=extra_thirds<=16:raise web.HTTPBadRequest(text='Beste Dritte: 0–16 Spieler')
    if extra_thirds and (fmt!='groups' or not follow or q=='all'):
        raise web.HTTPBadRequest(text='Beste Dritte nur bei Gruppenvorrunde mit Finalrunde und begrenzter Grundqualifikation')
    if extra_thirds and extra_thirds>n:raise web.HTTPBadRequest(text='Es gibt nicht genügend Gruppen für so viele beste Drittplatzierte')
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
    # Round-specific match lengths; preliminary round may be drawn, KO cannot.
    stages=('group','quarterfinal','semifinal','third_place','final')
    round_lengths={}
    for stage in stages:
        value=d.get('round_lengths',{}).get(stage) if isinstance(d.get('round_lengths'),dict) else None
        if value is None:continue
        try:value=int(value)
        except (TypeError,ValueError):raise web.HTTPBadRequest(text='Ungültige Matchlänge: '+stage)
        if not 1<=value<=101:raise web.HTTPBadRequest(text='Best of X muss 1–101 sein')
        if stage!='group' and value%2==0:raise web.HTTPBadRequest(text='K.O.-Matchlängen müssen ungerade sein')
        round_lengths[stage]=value
    third_place=bool(d.get('third_place',False))
    if third_place and (not follow or nextfmt not in ('single_ko','double_ko')):
        raise web.HTTPBadRequest(text='Spiel um Platz 3 benötigt eine KO-Finalrunde')
    return {'format':fmt,'ids':ids,'group_count':n,'rules':prelim,'double_round':bool(d.get('double_round',False)),
            'follow':follow,'consolation':consolation,'round_lengths':round_lengths,'third_place':third_place,'qualifiers':q,'best_third_count':extra_thirds,'follow_format':nextfmt,'consolation_format':comfort,'follow_group_count':int(d.get('follow_group_count',1)), 'consolation_group_count':int(d.get('consolation_group_count',1))}

async def setup(req):
    a=await actor(req);d=await body(req);title=str(d.get('title','')).strip()
    if not 1<=len(title)<=150:raise web.HTTPBadRequest(text='Turniername erforderlich')
    spec=validate_plan(d)
    if a['role']=='member' and a['player_id'] not in spec['ids']:
        raise web.HTTPForbidden(text='Mitglieder können nur eigene Trainingsturniere erstellen')
    if spec['rules']['mode']=='legs' and spec['round_lengths'].get('group'):
        spec['rules']={**spec['rules'],'max_legs':spec['round_lengths']['group'],'allow_draw':spec['round_lengths']['group']%2==0}
    config={'auto_tournament':True,'format':spec['format'],'training_match':spec['rules'],
            'double_round':spec['double_round'],'follow':spec['follow'],'consolation':spec['consolation'],'round_lengths':spec['round_lengths'],'third_place':spec['third_place'],
            'qualifiers':spec['qualifiers'],'best_third_count':spec['best_third_count'],'follow_format':spec['follow_format'],
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
        if spec['rules']['mode']=='legs' and spec['round_lengths'].get('group'):
            spec['rules']={**spec['rules'],'max_legs':spec['round_lengths']['group'],'allow_draw':spec['round_lengths']['group']%2==0}
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
            if spec['rules']['mode']=='legs':
                initial_key='final' if len(spec['ids'])<=2 else 'semifinal' if len(spec['ids'])<=4 else 'quarterfinal'
                spec['rules']={**spec['rules'],'max_legs':int(spec['round_lengths'].get(initial_key,spec['rules']['max_legs']))}
            pairs=bracket_pairs(spec['ids'])
            byes=[p for x,y in pairs if not(x and y) for p in (x,y) if p]
            await db.execute(f'UPDATE {SCHEMA}.phases SET rules=rules || $2::jsonb WHERE id=$1',phase,json.dumps({'bye_players':[str(p) for p in byes]}))
            for i,(p1,p2) in enumerate(pairs):
                if p1 is None or p2 is None:continue
                await db.execute(f'''INSERT INTO {SCHEMA}.matches(competition_id,phase_id,round_number,bracket_position,player1_id,player2_id,rules)
                  VALUES($1,$2,1,$3,$4,$5,$6::jsonb)''',cid,phase,i+1,p1,p2,json.dumps({**spec['rules'],'bracket':'winner'} if spec['format']=='double_ko' else spec['rules']))
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
             VALUES($1,$2,1,$3,$4,$5,$6::jsonb)''',cid,ph,i+1,p1,p2,json.dumps({**match_rules,'bracket':'winner'} if fmt=='double_ko' else match_rules));count+=1
    return count

def rank_wildcards(candidates):
    """Rank first eliminated player of each preliminary group fairly.

    Normalize by matches played so unequal group sizes do not confer an advantage.
    Caller provides (player_id, table_row, group_sort_order).
    """
    def metrics(item):
        _,row,order=item
        n=max(1,int(row['played']))
        return (row['points']/n, (row['legs_for']-row['legs_against'])/n, row['legs_for']/n)
    return sorted(candidates,key=lambda item:(-metrics(item)[0],-metrics(item)[1],-metrics(item)[2],item[2],str(item[0])))


def double_ko_next_matches(participants, allrows):
    """Return (bracket, p1, p2) for the next DOUBLE KO wave.

    One loss moves a player into the lower bracket; the second eliminates.
    The undefeated player only meets the lower-bracket winner in the grand final.
    Each participant plays at most once per wave. Past opponents are avoided
    until unavoidable (notably the grand final / reset).
    """
    losses={p:0 for p in participants}
    met=set()
    last_round={p:0 for p in participants}
    newly_dropped=set()
    for m in allrows:
        w=winner(m)
        if w is None:
            raise ValueError('Unvollständiges oder unentschiedenes KO-Ergebnis')
        p1,p2=m['player1_id'],m['player2_id']
        if p1 not in losses or p2 not in losses:
            raise ValueError('Unbekannter Teilnehmer im KO-Baum')
        if losses[p1]>=2 or losses[p2]>=2:
            raise ValueError('Ein bereits ausgeschiedener Spieler wurde erneut angesetzt')
        l=p2 if w==p1 else p1
        losses[l]+=1
        if losses[l]==1 and int(m['round_number'])==int(allrows[-1]['round_number']):
            newly_dropped.add(l)
        met.add(frozenset((p1,p2)))
        last_round[p1]=last_round[p2]=int(m['round_number'])
    undefeated=[p for p in participants if losses[p]==0]
    lower=[p for p in participants if losses[p]==1]
    if len(undefeated)+len(lower)<=1:
        return []
    if len(undefeated)==1 and len(lower)==1:
        # First meeting of finalists or reset match if the previously undefeated
        # player lost the first grand final.
        return [('grand_final',undefeated[0],lower[0])] if undefeated else []
    if not undefeated and len(lower)==2:
        # A reset final: both finalists now have exactly one loss.
        return [('grand_final_reset',lower[0],lower[1])]
    upcoming=[]
    def pair_group(people,kind):
        pool=sorted(people,key=lambda p:(last_round[p],str(p)))
        # The fresh loser of the upper-bracket final waits until the lower
        # bracket has produced its challenger (when there are three players).
        if kind=='loser' and len(pool)%2 and len(pool)>=3:
            waiting=next((p for p in pool if p in newly_dropped),None)
            if waiting is not None:pool.remove(waiting)
        while len(pool)>1:
            p=pool.pop(0)
            # Favor opponents not yet played, with the oldest last appearance.
            q=min(pool,key=lambda x:(frozenset((p,x)) in met,last_round[x],str(x)))
            pool.remove(q)
            upcoming.append((kind,p,q))
    pair_group(undefeated,'winner')
    pair_group(lower,'loser')
    return upcoming


async def progress(req,cid):
    """Run after score commit, serialize by competition row. Idempotent across tablets."""
    async with pool(req).acquire() as db:
      async with db.transaction():
        c=await db.fetchrow(f'''SELECT id,rules,status FROM {SCHEMA}.competitions
          WHERE id=$1 AND kind IN ('training_tournament','final_tournament') AND deleted_at IS NULL FOR UPDATE''',cid)
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
                selected=[];rest=[];wildcards=[]
                for order,g in enumerate(groups):
                    members=await db.fetch(f'''SELECT e.player_id FROM {SCHEMA}.group_members gm
                     JOIN {SCHEMA}.entries e ON e.id=gm.entry_id WHERE gm.group_id=$1''',g['id'])
                    ms=await db.fetch(f'''SELECT player1_id,player2_id,status,legs1,legs2,sets1,sets2 FROM {SCHEMA}.matches
                      WHERE group_id=$1''',g['id'])
                    ranks=rank_rows([dict(m) for m in ms],[p['player_id'] for p in members])
                    selected.extend(p['player_id'] for p in ranks[:n])
                    rest.extend(p['player_id'] for p in ranks[n:])
                    if len(ranks)>n:wildcards.append((ranks[n]['player_id'],ranks[n],order))
                extra=int(cfg.get('best_third_count',0) or 0)
                if extra:
                    if extra>len(wildcards):raise web.HTTPConflict(text='Nicht genügend Drittplatzierte für die angegebene Wildcard-Anzahl')
                    best=rank_wildcards(wildcards)
                    manual=[UUID(str(x)) for x in cfg.get('best_third_manual_ids',[])]
                    if manual:
                        available={x[0] for x in wildcards}
                        if len(manual)!=extra or len(set(manual))!=extra or not set(manual).issubset(available):
                            raise web.HTTPConflict(text='Manuelle Nachrücker passen nicht zur abgeschlossenen Vorrunde')
                    # Do not silently draw lots at a perfect statistical tie on the cutoff.
                    if not manual and len(best)>extra:
                        a=best[extra-1][1];b=best[extra][1]
                        def key(row):
                            count=max(1,row['played'])
                            return (row['points']/count,(row['legs_for']-row['legs_against'])/count,row['legs_for']/count)
                        if key(a)==key(b):
                            raise web.HTTPConflict(text='Gleichstand der besten Drittplatzierten an der Qualifikationsgrenze – manuelle Entscheidung erforderlich')
                    additional=set(manual) if manual else {x[0] for x in best[:extra]}
                    selected.extend(manual if manual else [x[0] for x in best[:extra]])
                    rest=[pid for pid in rest if pid not in additional]
                if len(selected)<2:raise web.HTTPConflict(text='Weniger als zwei qualifizierte Spieler')
                final_rules={**cfg['training_match']}
                if final_rules.get('mode')=='legs':
                    initial_key='final' if len(selected)<=2 else 'semifinal' if len(selected)<=4 else 'quarterfinal'
                    final_rules['max_legs']=int(cfg.get('round_lengths',{}).get(initial_key,final_rules['max_legs']))
                await _make_stage(db,cid,'final',selected,cfg.get('follow_format','single_ko'),final_rules,cfg.get('follow_group_count',1))
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
            if any(m['legs1']==m['legs2'] and not (m['sets1'] or m['sets2']) for m in rows):
                import logging
                logging.error('K.O.-Runde mit Unentschieden kann nicht fortgeschrieben werden: phase=%s round=%s',ph['id'],mx)
                continue
            allrows=await db.fetch(f'SELECT * FROM {SCHEMA}.matches WHERE phase_id=$1 ORDER BY round_number,bracket_position',ph['id'])
            participants=[UUID(p) for p in pr.get('participants',[])]
            if fmt=='single_ko':
                remaining=[winner(m) for m in rows]
                if mx==1:remaining+= [UUID(x) for x in pr.get('bye_players',[])]
            else:
                try:
                    double_pairs=double_ko_next_matches(participants,allrows)
                except ValueError as exc:
                    logging.error('Doppel-KO konnte nicht fortgesetzt werden: %s',exc)
                    continue
                if not double_pairs:
                    await db.execute(f"UPDATE {SCHEMA}.phases SET status='closed',closed_at=now() WHERE id=$1",ph['id'])
                    continue
                rules={**pr.get('match_rules',cfg['training_match']),'allow_draw':False}
                if rules.get('mode')=='legs':
                    is_final=double_pairs[0][0].startswith('grand_final')
                    length_key='final' if is_final else 'semifinal' if len(double_pairs)<=2 else 'quarterfinal'
                    value=cfg.get('round_lengths',{}).get(length_key) if pr.get('stage')=='final' else None
                    if value is not None:rules['max_legs']=int(value)
                for i,(bracket,p1,p2) in enumerate(double_pairs):
                    match_rules={**rules,'bracket':bracket}
                    await db.execute(f"""INSERT INTO {SCHEMA}.matches(competition_id,phase_id,round_number,bracket_position,player1_id,player2_id,rules)
                     VALUES($1,$2,$3,$4,$5,$6,$7::jsonb)""",cid,ph['id'],mx+1,i+1,p1,p2,json.dumps(match_rules))
                continue
            remaining=[p for p in remaining if p is not None]
            if len(remaining)<=1:
                await db.execute(f"UPDATE {SCHEMA}.phases SET status='closed',closed_at=now() WHERE id=$1",ph['id']);continue
            rules={**pr.get('match_rules',cfg['training_match'])}
            if pr.get('stage')=='final' and rules.get('mode')=='legs':
                # Two remaining = final; previous two ties = semifinals.
                key='final' if len(remaining)==2 else 'semifinal' if len(remaining)<=4 else 'quarterfinal'
                value=cfg.get('round_lengths',{}).get(key)
                if value is not None:rules['max_legs']=int(value)
            if pr.get('stage')=='final' and cfg.get('third_place') and len(rows)==2 and len(remaining)==2 and fmt=='single_ko':
                losers=[m['player2_id'] if winner(m)==m['player1_id'] else m['player1_id'] for m in rows]
                existing=await db.fetchval(f"SELECT count(*) FROM {SCHEMA}.phases WHERE competition_id=$1 AND rules->>'stage'='third_place'",cid)
                if not existing and len(set(losers))==2:
                    tp={**cfg['training_match'],'allow_draw':False}
                    if tp.get('mode')=='legs':
                        tp['max_legs']=int(cfg.get('round_lengths',{}).get('third_place',5))
                        if tp['max_legs']%2==0:tp['max_legs']+=1
                    pid=await db.fetchval(f"INSERT INTO {SCHEMA}.phases(competition_id,name,kind,phase_order,status,rules) VALUES($1,'Spiel um Platz 3','knockout',4,'open',$2::jsonb) RETURNING id",cid,json.dumps({'stage':'third_place','format':'single_ko','participants':[str(x) for x in losers],'match_rules':tp}))
                    await db.execute(f"INSERT INTO {SCHEMA}.matches(competition_id,phase_id,round_number,bracket_position,player1_id,player2_id,rules) VALUES($1,$2,1,1,$3,$4,$5::jsonb)",cid,pid,losers[0],losers[1],json.dumps(tp))
            next_pairs=[(x,y) for x,y in bracket_pairs(remaining) if x and y]
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
    # Placement priority: final phase > KO round > preliminary group performance.
    await actor(req)
    cid=uid(req.match_info['cid'])
    async with pool(req).acquire() as db:
        c=await db.fetchrow(f'SELECT title,kind,status FROM {SCHEMA}.competitions WHERE id=$1 AND deleted_at IS NULL',cid)
        if not c or c['kind']=='ladder':raise web.HTTPNotFound()
        phases=await db.fetch(f'SELECT id,name,kind,phase_order,rules FROM {SCHEMA}.phases WHERE competition_id=$1 ORDER BY phase_order',cid)
        matches=await db.fetch(f'''SELECT m.*,p.phase_order,p.kind AS phase_kind,p.name AS phase_name,p.rules AS phase_rules
          FROM {SCHEMA}.matches m JOIN {SCHEMA}.phases p ON p.id=m.phase_id
          WHERE m.competition_id=$1 AND m.status='finished' ORDER BY p.phase_order,m.round_number''',cid)
        players=await db.fetch(f'''SELECT p.id,p.display_name FROM {SCHEMA}.entries e JOIN {SCHEMA}.players p ON p.id=e.player_id
          WHERE e.competition_id=$1''',cid)
    records={p['id']:{'player_id':p['id'],'name':p['display_name'],'wins':0,'losses':0,
        'points':0,'darts':0,'stage':-1,'round':-1,'reached':'Vorrunde','is_winner':False,'rank_group':0,
        'rank_key':(-1,-1,-1)} for p in players}
    if not records:return response({'title':c['title'],'finished':c['status']=='finished','placements':[],'provisional':True})
    # Phase order alone cannot be used as merit: consolation often has a higher phase_order than finals.
    stage_type={}
    for ph in phases:
        rules=as_json(ph['rules']);stage=rules.get('stage') or ('consolation' if 'trost' in ph['name'].lower() else 'final' if ph['phase_order']>1 and ('final' in ph['name'].lower() or ph['kind']=='knockout') else 'preliminary')
        stage_type[ph['id']]=stage
        participants=[UUID(x) for x in rules.get('participants',[]) if x]
        merit={'preliminary':1,'consolation':2,'final':3}.get(stage,1)
        for pid in participants:
            if pid in records and merit>records[pid]['stage']:
                records[pid].update(stage=merit,round=0,reached={'preliminary':'Vorrunde','final':'Finalrunde','consolation':'Trostrunde'}.get(stage,ph['name']))
    knockout_phases={p['id'] for p in phases if p['kind']=='knockout'}
    by_phase={}
    for m in matches:
        by_phase.setdefault(m['phase_id'],[]).append(m)
        stage=stage_type.get(m['phase_id'],'preliminary')
        merit={'preliminary':1,'consolation':2,'final':3}.get(stage,1)
        round_num=int(m['round_number'] or 1)
        w=winner(m)
        for idx,pid in enumerate((m['player1_id'],m['player2_id'])):
            if pid not in records:continue
            r=records[pid];r['wins']+=int(w==pid);r['losses']+=int(w is not None and w!=pid)
            visits=as_json(m['state']).get('visits',[])
            for v in visits:
                if v.get('player')==idx:
                    r['points']+=0 if v.get('bust') else int(v.get('score',0) or 0)
                    r['darts']+=int(v.get('darts',3) or 3)
            if merit>r['stage'] or (merit==r['stage'] and round_num>=r['round']):
                r['stage']=merit;r['round']=round_num;r['is_winner']=bool(w==pid)
                r['reached']=('Finalrunde' if stage=='final' else 'Trostrunde' if stage=='consolation' else 'Vorrunde')
    # KO matches: elimination round outranks all earlier rounds; winner of the last final is champion.
    for ph in phases:
        ms=by_phase.get(ph['id'],[])
        if not ms:continue
        stage=stage_type.get(ph['id'],'preliminary');merit={'preliminary':1,'consolation':2,'final':3}.get(stage,1)
        if ph['id'] in knockout_phases:
            last=max(int(m['round_number'] or 1) for m in ms)
            for m in ms:
                rnd=int(m['round_number'] or 1);w=winner(m)
                for pid in (m['player1_id'],m['player2_id']):
                    if pid not in records:continue
                    r=records[pid]
                    # A round winner who advances must not be ranked merely by prior wins.
                    # Players eliminated in the same semifinal receive the same rank key.
                    if r['stage']==merit and r['round']==rnd:
                        r['rank_key']=(merit,rnd,1 if w==pid and rnd==last else 0)
                        if rnd==last and len([x for x in ms if int(x['round_number'] or 1)==last])==1:
                            r['reached']='Finale'
                        elif rnd==last-1 and len([x for x in ms if int(x['round_number'] or 1)==rnd])==2:
                            r['reached']='Halbfinale'
                        else:r['reached']='KO-Runde '+str(rnd)
        else:
            # League/group-only stage: rank according to wins, then leg differential.
            for r in records.values():
                if r['stage']!=merit:continue
                own=[m for m in ms if r['player_id'] in (m['player1_id'],m['player2_id'])]
                wins=sum(winner(m)==r['player_id'] for m in own)
                legdiff=sum((int(m['legs1'] or 0)-int(m['legs2'] or 0))*(1 if m['player1_id']==r['player_id'] else -1) for m in own)
                if r['rank_key'][0]<merit:r['rank_key']=(merit,0,wins*1000+legdiff)
    for r in records.values():
        if r['rank_key'][0]<0:r['rank_key']=(r['stage'],r['round'],int(r['is_winner']))
    # Rank keys preserve ties where no placement match was played.
    ordered=sorted(records.values(),key=lambda x:(-x['rank_key'][0],-x['rank_key'][1],-x['rank_key'][2],x['name'].casefold()))
    last_key=None;place=0
    for idx,r in enumerate(ordered,1):
        if r['rank_key']!=last_key:place=idx;last_key=r['rank_key']
        r['place']=place;r['average']=round(3*r['points']/r['darts'],2) if r['darts'] else None
        r['tied']=False
    counts={}
    for r in ordered:counts[r['place']]=counts.get(r['place'],0)+1
    for r in ordered:r['tied']=counts[r['place']]>1
    return response({'title':c['title'],'finished':c['status']=='finished','placements':ordered,'provisional':c['status']!='finished'})
