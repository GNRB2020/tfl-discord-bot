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
from .live_stats import live_averages

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
            VALUES($1,'Vorrunde',$2,1,'open',$3::jsonb) RETURNING id''',cid,kind,json.dumps({'stage':'preliminary','format':spec['format'],'participants':[str(x) for x in spec['ids']],'match_rules':spec['rules'],
                        **({'bracket_released':False} if kind=='knockout' else {})}))
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
                  VALUES($1,$2,1,$3,$4,$5,$6::jsonb)''',cid,phase,i+1,p1,p2,json.dumps(spec['rules']))
                created+=1
        if not created:raise web.HTTPBadRequest(text='Keine Begegnungen erzeugt')
    return response({'id':cid,'created':created,'groups':spec['group_count'],'automatic':True},201)


def winner(m):
    s1,s2=(m['sets1'],m['sets2']) if (m['sets1'] or m['sets2']) else (m['legs1'],m['legs2'])
    if s1 is None or s2 is None or s1==s2:return None
    return m['player1_id'] if s1>s2 else m['player2_id']

async def _make_stage(db,cid,stage,ids,fmt,match_rules,ngroups=1,double_round=False,origin_groups=None):
    if fmt in ('single_ko','double_ko'):
        match_rules={**match_rules,'allow_draw':False}
        if match_rules['mode']=='legs' and match_rules['max_legs']%2==0:
            match_rules['max_legs']+=1
    order=2 if stage=='final' else 3
    stage_kind='groups' if fmt in ('groups','league') else 'knockout'
    stage_rules={'stage':stage,'format':fmt,'participants':[str(p) for p in ids],
                 'match_rules':match_rules,'origin_groups':origin_groups or {},
                 **({'bracket_released':False} if stage_kind=='knockout' else {})}
    # Admins sometimes created an empty K.O. placeholder after the group draw.
    # Reuse it instead of silently assuming the next round already exists.
    placeholder=await db.fetchrow(f'''SELECT id,kind,rules FROM {SCHEMA}.phases
      WHERE competition_id=$1 AND phase_order=$2 FOR UPDATE''',cid,order)
    if placeholder:
        if as_json(placeholder['rules']).get('stage') or await db.fetchval(
          f'SELECT EXISTS(SELECT 1 FROM {SCHEMA}.matches WHERE phase_id=$1)',placeholder['id']):
            raise web.HTTPConflict(text='Die Folgerunde enthält bereits Daten; automatische Auslosung abgebrochen')
        if await db.fetchval(f'SELECT EXISTS(SELECT 1 FROM {SCHEMA}.groups WHERE phase_id=$1)',placeholder['id']):
            raise web.HTTPConflict(text='Die Folgerunde enthält manuell angelegte Gruppen; bitte zuerst prüfen')
        ph=placeholder['id']
        await db.execute(f'''UPDATE {SCHEMA}.phases SET name=$2,kind=$3,status='open',rules=$4::jsonb,
            closed_at=NULL,closed_by=NULL WHERE id=$1''',ph,
            'Finalrunde' if stage=='final' else 'Trostrunde',stage_kind,json.dumps(stage_rules))
    else:
        ph=await db.fetchval(f'''INSERT INTO {SCHEMA}.phases(competition_id,name,kind,phase_order,status,rules)
          VALUES($1,$2,$3,$4,'open',$5::jsonb) RETURNING id''',cid,'Finalrunde' if stage=='final' else 'Trostrunde',
          stage_kind,order,json.dumps(stage_rules))
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
        if origin_groups:
            ids=spread_groups_in_bracket(ids,origin_groups)
        pairs=bracket_pairs(ids)
        byes=[p for x,y in pairs if not(x and y) for p in (x,y) if p]
        await db.execute(f'UPDATE {SCHEMA}.phases SET rules=rules || $2::jsonb WHERE id=$1',ph,json.dumps({'bye_players':[str(p) for p in byes]}))
        for i,(p1,p2) in enumerate(pairs):
            if p1 is None or p2 is None:continue
            await db.execute(f'''INSERT INTO {SCHEMA}.matches(competition_id,phase_id,round_number,bracket_position,player1_id,player2_id,rules)
             VALUES($1,$2,1,$3,$4,$5,$6::jsonb)''',cid,ph,i+1,p1,p2,json.dumps(match_rules));count+=1
    return count

def spread_groups_in_bracket(ids, origin_groups):
    """Prefer early cross-group games; preserve entrants and do not manufacture rematches.

    Optimize standard bracket slots (first round, quarters, halves), with stronger
    penalties for rematches in earlier stages. Only the seed order is rearranged.
    """
    from .rules import bracket_pairs
    ids=list(ids)
    if len(ids)<3 or not origin_groups:return ids
    def cost(seq):
        n=1<<(len(seq)-1).bit_length()
        positions=[1,2]
        while len(positions)<n:
            total=2*len(positions)+1
            positions=[x for x in positions for x in (x,total-x)]
        slots=[seq[k-1] if k<=len(seq) else None for k in positions]
        penalty=0
        for size,weight in ((2,1000),(4,80),(8,15),(16,3)):
            if size>n:continue
            for k in range(0,n,size):
                groups=[origin_groups.get(str(x)) for x in slots[k:k+size] if x]
                for i,g in enumerate(groups):
                    penalty+=sum(weight for b in groups[i+1:] if b and b==g)
        return penalty
    best=cost(ids)
    # Bounded deterministic improvement, avoids randomly reshuffling after a result.
    for _ in range(3):
        improved=False
        if best==0:break
        for i in range(len(ids)):
            for j in range(i+1,len(ids)):
                if origin_groups.get(str(ids[i]))==origin_groups.get(str(ids[j])):continue
                ids[i],ids[j]=ids[j],ids[i]
                score=cost(ids)
                if score<best:
                    best=score;improved=True
                else:
                    ids[i],ids[j]=ids[j],ids[i]
        if not improved:break
    return ids


def round_match_rules(rules, lengths, key):
    result=dict(rules)
    value=lengths.get(key)
    if value is not None:
        if result.get('mode')=='sets':result['best_of_sets']=int(value)
        else:result['max_legs']=int(value)
    return result


def rank_wildcards(candidates):
    """Rank first eliminated player of each preliminary group fairly.

    Normalize by matches played so unequal group sizes do not confer an advantage.
    Caller provides (player_id, table_row, group_sort_order).
    """
    def metrics(item):
        row=item[1];order=item[2]
        n=max(1,int(row['played']))
        return (row['points']/n, (row['legs_for']-row['legs_against'])/n, row['legs_for']/n)
    return sorted(candidates,key=lambda item:(item[3] if len(item)>3 else 0,-metrics(item)[0],-metrics(item)[1],-metrics(item)[2],item[2],str(item[0])))


async def progress(req,cid):
    """Run after score commit, serialize by competition row. Idempotent across tablets."""
    async with pool(req).acquire() as db:
      async with db.transaction():
        c=await db.fetchrow(f'''SELECT id,kind,rules,status FROM {SCHEMA}.competitions
          WHERE id=$1 AND kind IN ('training_tournament','final_tournament','league','cup','vm') AND deleted_at IS NULL FOR UPDATE''',cid)
        if not c or c['status'] not in ('active','draft'):return
        cfg=as_json(c['rules']);
        if not cfg.get('auto_tournament'):return
        if c['kind']=='cup':
            # Also protect older Stingray Cups that were created before fixed Bo5/Bo5 rules.
            from .competition_wizard import CUP_FIXED, ROUND_NAMES
            cfg['ko_match']={**CUP_FIXED}
            cfg['training_match']={**CUP_FIXED}
            cfg['round_lengths']={name:5 for name in ROUND_NAMES}
        phases=await db.fetch(f'SELECT id,phase_order,kind,rules,status FROM {SCHEMA}.phases WHERE competition_id=$1 ORDER BY phase_order',cid)
        if not phases:return
        pre=phases[0]
        pending=await db.fetchval(f"SELECT count(*) FROM {SCHEMA}.matches WHERE phase_id=$1 AND status<>'finished'",pre['id'])
        total=await db.fetchval(f'SELECT count(*) FROM {SCHEMA}.matches WHERE phase_id=$1',pre['id'])
        # An empty manually added 'KO Runde' must not suppress auto advancement.
        follow_phases=[p for p in phases if p['phase_order']>pre['phase_order']]
        has_prepared_follow=any(as_json(p['rules']).get('stage') for p in follow_phases)
        has_started_follow=False
        if follow_phases and not has_prepared_follow:
            has_started_follow=bool(await db.fetchval(f'''SELECT EXISTS(
                SELECT 1 FROM {SCHEMA}.matches m JOIN {SCHEMA}.phases ph ON ph.id=m.phase_id
                WHERE ph.competition_id=$1 AND ph.phase_order>$2)''',cid,pre['phase_order']))
        if not pending and total and not has_prepared_follow and not has_started_follow:
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
                    for place in range(n,len(ranks)):
                        wildcards.append((ranks[place]['player_id'],ranks[place],order,place))
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
                        if best[extra-1][3]==best[extra][3] and key(a)==key(b):
                            raise web.HTTPConflict(text='Gleichstand der besten Drittplatzierten an der Qualifikationsgrenze – manuelle Entscheidung erforderlich')
                    additional=set(manual) if manual else {x[0] for x in best[:extra]}
                    selected.extend(manual if manual else [x[0] for x in best[:extra]])
                    rest=[pid for pid in rest if pid not in additional]
                if len(selected)<2:raise web.HTTPConflict(text='Weniger als zwei qualifizierte Spieler')
                final_rules={**cfg.get('ko_match',cfg['training_match'])}
                initial_key='final' if len(selected)<=2 else 'semifinal' if len(selected)<=4 else 'quarterfinal' if len(selected)<=8 else 'round16' if len(selected)<=16 else 'round32' if len(selected)<=32 else 'first_round'
                final_rules=round_match_rules(final_rules,cfg.get('round_lengths',{}),initial_key)
                # Keep participants from the same preliminary group apart in the bracket where possible.
                first_group={}
                for g in groups:
                    mem=await db.fetch(f'''SELECT e.player_id FROM {SCHEMA}.group_members gm JOIN {SCHEMA}.entries e ON e.id=gm.entry_id WHERE gm.group_id=$1''',g['id'])
                    for p in mem:first_group[str(p['player_id'])]=str(g['id'])
                await _make_stage(db,cid,'final',selected,cfg.get('follow_format','single_ko'),final_rules,cfg.get('follow_group_count',1), origin_groups=first_group)
                if cfg.get('consolation') and len(rest)>=2:
                    await _make_stage(db,cid,'consolation',rest,cfg.get('consolation_format','single_ko'),cfg.get('ko_match',cfg['training_match']),cfg.get('consolation_group_count',1),origin_groups=first_group)
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
                loss={p:0 for p in participants}
                for m in allrows:
                    w=winner(m)
                    if w is None:return
                    l=m['player2_id'] if w==m['player1_id'] else m['player1_id'];loss[l]=loss.get(l,0)+1
                remaining=[p for p in participants if loss.get(p,0)<2]
            remaining=[p for p in remaining if p is not None]
            if len(remaining)<=1:
                await db.execute(f"UPDATE {SCHEMA}.phases SET status='closed',closed_at=now() WHERE id=$1",ph['id']);continue
            rules={**pr.get('match_rules',cfg['training_match'])}
            if pr.get('stage')=='final':
                key='final' if len(remaining)==2 else 'semifinal' if len(remaining)<=4 else 'quarterfinal' if len(remaining)<=8 else 'round16' if len(remaining)<=16 else 'round32'
                rules=round_match_rules(rules,cfg.get('round_lengths',{}),key)
            if pr.get('stage')=='final' and cfg.get('third_place') and len(rows)==2 and len(remaining)==2 and fmt=='single_ko':
                losers=[m['player2_id'] if winner(m)==m['player1_id'] else m['player1_id'] for m in rows]
                existing=await db.fetchval(f"SELECT count(*) FROM {SCHEMA}.phases WHERE competition_id=$1 AND rules->>'stage'='third_place'",cid)
                if not existing and len(set(losers))==2:
                    tp={**cfg.get('ko_match',cfg['training_match']),'allow_draw':False}
                    tp=round_match_rules(tp,cfg.get('round_lengths',{}),'third_place')
                    if tp['mode']=='legs' and tp['max_legs']%2==0:tp['max_legs']+=1
                    pid=await db.fetchval(f"INSERT INTO {SCHEMA}.phases(competition_id,name,kind,phase_order,status,rules) VALUES($1,'Spiel um Platz 3','knockout',4,'open',$2::jsonb) RETURNING id",cid,json.dumps({'stage':'third_place','format':'single_ko','participants':[str(x) for x in losers],'match_rules':tp,'bracket_released':False}))
                    await db.execute(f"INSERT INTO {SCHEMA}.matches(competition_id,phase_id,round_number,bracket_position,player1_id,player2_id,rules) VALUES($1,$2,1,1,$3,$4,$5::jsonb)",cid,pid,losers[0],losers[1],json.dumps(tp))
            if pr.get('origin_groups'):
                remaining=spread_groups_in_bracket(remaining,pr['origin_groups'])
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


async def wildcard_overview(req):
    # Read-only comparison; same ranking as the automatic progression.
    await actor(req)
    cid=uid(req.match_info['cid'])
    async with pool(req).acquire() as db:
        c=await db.fetchrow(f'SELECT kind,rules FROM {SCHEMA}.competitions WHERE id=$1 AND deleted_at IS NULL',cid)
        if not c:raise web.HTTPNotFound()
        cfg=as_json(c['rules'])
        pre=await db.fetchrow(f'''SELECT id FROM {SCHEMA}.phases
            WHERE competition_id=$1 ORDER BY phase_order LIMIT 1''',cid)
        if not pre or not cfg.get('follow') or not int(cfg.get('best_third_count',0) or 0):
            return response({'candidates':[],'wildcard_count':0,'completed':False})
        groups=await db.fetch(f'SELECT id,name,sort_order FROM {SCHEMA}.groups WHERE phase_id=$1 ORDER BY sort_order',pre['id'])
        n=int(cfg.get('qualifiers',1)) if str(cfg.get('qualifiers','1'))!='all' else 99999
        candidates=[]
        names={}
        for g in groups:
            people=await db.fetch(f'''SELECT e.player_id,p.display_name FROM {SCHEMA}.group_members gm
                JOIN {SCHEMA}.entries e ON e.id=gm.entry_id JOIN {SCHEMA}.players p ON p.id=e.player_id
                WHERE gm.group_id=$1''',g['id'])
            names.update({p['player_id']:p['display_name'] for p in people})
            ms=await db.fetch(f'''SELECT player1_id,player2_id,status,legs1,legs2,sets1,sets2
               FROM {SCHEMA}.matches WHERE group_id=$1''',g['id'])
            standings=rank_rows([dict(m) for m in ms],[p['player_id'] for p in people])
            for place,row in enumerate(standings[n:],start=n):
                candidates.append((row['player_id'],row,g['sort_order'],place,g['name']))
        ranked=rank_wildcards(candidates)
        count=int(cfg['best_third_count'])
        completed=bool(await db.fetchval(f'''SELECT count(*)=0 FROM {SCHEMA}.matches
            WHERE phase_id=$1 AND status<>'finished' ''',pre['id']))
        manual=set(str(x) for x in cfg.get('best_third_manual_ids',[]))
        def score(item):
            r=item[1];played=max(1,int(r['played']))
            return (int(item[3]),int(r['points'])/played,(int(r['legs_for'])-int(r['legs_against']))/played,int(r['legs_for'])/played)
        decision_required=(completed and not manual and len(ranked)>count and count>0
            and score(ranked[count-1])==score(ranked[count]))
        out=[]
        for i,(pid,row,_,place,gname) in enumerate(ranked):
            played=max(1,int(row['played']))
            out.append({'rank':i+1,'player_id':str(pid),'name':names.get(pid,''),'group':gname,
                'group_rank':place+1,'played':row['played'],'points':row['points'],
                'points_per_match':round(int(row['points'])/played,3),
                'leg_difference':int(row['legs_for'])-int(row['legs_against']),
                'leg_difference_per_match':round((int(row['legs_for'])-int(row['legs_against']))/played,3),
                'legs_for':row['legs_for'],'legs_for_per_match':round(int(row['legs_for'])/played,3),
                'selected':str(pid) in manual if manual else i<count,
                'cutoff_tie':decision_required and score(ranked[count-1])==score((pid,row,0,place))})
        return response({'candidates':out,'wildcard_count':count,'completed':completed,
            'decision_required':decision_required})

async def retry_progress(req):
    # Explicitly recover a completed preliminary round whose advancement was interrupted.
    account=await actor(req);cid=uid(req.match_info['cid']);await body(req)
    from .api import require_manager
    async with pool(req).acquire() as db:
        await require_manager(db,account,cid)
    await progress(req,cid)
    async with pool(req).acquire() as db:
        phases=await db.fetch(f'''SELECT id,phase_order,status,name FROM {SCHEMA}.phases
            WHERE competition_id=$1 ORDER BY phase_order''',cid)
        matches=await db.fetchval(f'''SELECT count(*) FROM {SCHEMA}.matches m
            JOIN {SCHEMA}.phases p ON p.id=m.phase_id
            WHERE p.competition_id=$1 AND p.phase_order>1''',cid)
    return response({'ok':True,'follow_matches':int(matches),'phases':[dict(p) for p in phases]})

async def live_games(req):
    await actor(req)
    async with pool(req).acquire() as db:
        rows=await db.fetch(f'''SELECT m.id,m.competition_id,c.title,c.kind,p1.display_name AS player1,p2.display_name AS player2,
           m.legs1,m.legs2,m.sets1,m.sets2,m.state,m.started_at FROM {SCHEMA}.matches m
           JOIN {SCHEMA}.competitions c ON c.id=m.competition_id AND c.deleted_at IS NULL
           JOIN {SCHEMA}.players p1 ON p1.id=m.player1_id JOIN {SCHEMA}.players p2 ON p2.id=m.player2_id
           WHERE m.status='running' ORDER BY m.started_at DESC LIMIT 22''')
    out=[]
    for r in rows:
        state=as_json(r['state'])
        # Bust consumes darts but awards zero points, like the main scorer.
        averages=live_averages(state.get('visits',[]))
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
