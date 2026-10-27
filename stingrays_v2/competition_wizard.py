"""Atomic setup of grouped Stingray competitions, with reviewed (not silently saved) draws.

No existing phase, match or result is ever deleted by this route.
"""
import json
from aiohttp import web
from .api import actor, body, uid, pool, response, SCHEMA, require_manager, as_json
from .rules import round_robin
from .tournament_extensions import validate_training_rules

FORMATS = {'single_ko', 'double_ko', 'groups', 'league'}
ROUND_NAMES = ('first_round', 'round32', 'round16', 'quarterfinal', 'semifinal', 'final', 'third_place')


def normalize(d, participants):
    if not isinstance(d, dict):
        raise web.HTTPBadRequest(text='Ungültige Turnierkonfiguration')
    try:
        groups=int(d.get('group_count', 2))
        qualifiers=int(d.get('qualifiers',2))
        wildcards=int(d.get('best_third_count',0))
        final_groups=int(d.get('follow_group_count',2))
        consolation_groups=int(d.get('consolation_group_count',2))
    except (ValueError, TypeError):
        raise web.HTTPBadRequest(text='Gruppen- und Qualifikationszahlen müssen ganze Zahlen sein')
    if not 1 <= groups <= min(50,participants//2):
        raise web.HTTPBadRequest(text='Mindestens zwei Spieler je Gruppe, maximal 50 Gruppen')
    if not 1 <= qualifiers <= min(16, (participants+groups-1)//groups):
        raise web.HTTPBadRequest(text='Ungültige Anzahl an Qualifikanten je Gruppe')
    follow=bool(d.get('follow'))
    consolation=bool(d.get('consolation'))
    if consolation and not follow:
        raise web.HTTPBadRequest(text='Trostrunde erfordert eine Hauptrunde')
    if (wildcards and not follow) or wildcards<0 or wildcards>groups:
        raise web.HTTPBadRequest(text='Zusätzliche Qualifikanten müssen aus einer Vorrunde stammen')
    if wildcards and qualifiers>=participants//groups:
        raise web.HTTPBadRequest(text='Für beste Nächstplatzierte muss mindestens ein Platz in jeder Gruppe frei bleiben')
    fformat=d.get('follow_format','single_ko')
    cformat=d.get('consolation_format','single_ko')
    if fformat not in FORMATS or cformat not in FORMATS:
        raise web.HTTPBadRequest(text='Ungültiger Modus der Folgerunde')
    if not 1<=final_groups<=16 or not 1<=consolation_groups<=16:
        raise web.HTTPBadRequest(text='Maximal 16 Gruppen in Folgerunden')
    if consolation and participants-qualifiers*groups-wildcards<2:
        raise web.HTTPBadRequest(text='Mindestens zwei Teilnehmer für die Trostrunde erforderlich')
    if follow and qualifiers*groups+wildcards<2:
        raise web.HTTPBadRequest(text='Mindestens zwei Finalteilnehmer erforderlich')
    if follow and fformat in ('groups','league') and qualifiers*groups+wildcards<2*final_groups:
        raise web.HTTPBadRequest(text='Zu wenige Finalteilnehmer für diese Gruppenzahl')
    rules=validate_training_rules(d.get('group_rules') or {}, elimination=False)
    ko_rules=validate_training_rules(d.get('ko_rules') or {'mode':'legs','max_legs':5}, elimination=True)
    lengths=d.get('round_lengths') or {}
    if not isinstance(lengths,dict):
        raise web.HTTPBadRequest(text='Ungültige Matchlängen')
    prepared={}
    for key in ROUND_NAMES:
        if key not in lengths:continue
        try:val=int(lengths[key])
        except (ValueError,TypeError):raise web.HTTPBadRequest(text='Ungültige Länge für '+key)
        if not 1<=val<=101 or val%2==0:
            raise web.HTTPBadRequest(text='K.O.-Runden müssen ein ungerades Best of X (1–101) haben')
        prepared[key]=val
    if ko_rules['mode']=='sets':
        # In this mode round_lengths refer to best-of-sets, not best-of-legs.
        prepared={k:v for k,v in prepared.items() if v%2==1}
    buckets=d.get('groups')
    if not isinstance(buckets,list) or len(buckets)!=groups or any(not isinstance(g,list) for g in buckets):
        raise web.HTTPBadRequest(text='Bitte erst die Gruppen auslosen und die Einteilung prüfen')
    normalized=[]
    for group in buckets:
        try:group_ids=[uid(pid) for pid in group]
        except Exception:raise web.HTTPBadRequest(text='Ungültige Teilnehmer in der Gruppeneinteilung')
        if len(group_ids)<2:raise web.HTTPBadRequest(text='Jede Gruppe muss mindestens zwei Personen enthalten')
        normalized.append(group_ids)
    return {'group_count':groups,'groups':normalized,'group_rules':rules,'ko_rules':ko_rules,
            'double_round':bool(d.get('double_round',False)), 'follow':follow,'consolation':consolation,
            'qualifiers':qualifiers,'best_third_count':wildcards,
            'follow_format':fformat,'consolation_format':cformat,
            'follow_group_count':final_groups,'consolation_group_count':consolation_groups,
            'round_lengths':prepared,'third_place':bool(d.get('third_place',False))}


async def create_group_plan(req):
    account=await actor(req); cid=uid(req.match_info['cid']);data=await body(req)
    async with pool(req).acquire() as db:
      async with db.transaction():
        await require_manager(db,account,cid)
        comp=await db.fetchrow(f'SELECT id,kind,status,rules FROM {SCHEMA}.competitions WHERE id=$1 AND deleted_at IS NULL FOR UPDATE',cid)
        if not comp or comp['kind'] not in ('league','cup','vm','training_tournament'):
            raise web.HTTPBadRequest(text='Assistent nur für Ligawettbewerbe, Cup, VM und Trainingsturniere')
        if comp['status'] in ('finished','archived'):
            raise web.HTTPConflict(text='Abgeschlossene Wettbewerbe können nicht neu ausgelost werden')
        has_phase=await db.fetchval(f'SELECT EXISTS(SELECT 1 FROM {SCHEMA}.phases WHERE competition_id=$1)',cid)
        if has_phase:
            raise web.HTTPConflict(text='Es sind bereits Phasen vorhanden. Bitte keine bestehende Auslosung überschreiben; nur neue Wettbewerbe ohne Phasen können hier automatisch eingerichtet werden.')
        entries=await db.fetch(f"SELECT id,player_id FROM {SCHEMA}.entries WHERE competition_id=$1 AND status<>'withdrawn'",cid)
        spec=normalize(data,len(entries))
        available={e['player_id'] for e in entries}
        flat=[p for g in spec['groups'] for p in g]
        if len(flat)!=len(entries) or len(set(flat))!=len(flat) or set(flat)!=available:
            raise web.HTTPBadRequest(text='Jeder angemeldete Spieler muss genau einer Gruppe zugeordnet sein')
        cfg=as_json(comp['rules'])
        cfg.update({'auto_tournament':True,'format':'groups','training_match':spec['group_rules'],
            'ko_match':spec['ko_rules'],'double_round':spec['double_round'],'follow':spec['follow'],
            'consolation':spec['consolation'],'qualifiers':str(spec['qualifiers']),
            'best_third_count':spec['best_third_count'],'follow_format':spec['follow_format'],
            'consolation_format':spec['consolation_format'],'follow_group_count':spec['follow_group_count'],
            'consolation_group_count':spec['consolation_group_count'],'round_lengths':spec['round_lengths'],
            'third_place':spec['third_place'],'guided_setup':True})
        await db.execute(f'UPDATE {SCHEMA}.competitions SET rules=$2::jsonb,status=$3 WHERE id=$1',cid,json.dumps(cfg),'active')
        phase=await db.fetchval(f'''INSERT INTO {SCHEMA}.phases(competition_id,name,kind,phase_order,status,rules)
            VALUES($1,'Gruppenrunde','groups',1,'open',$2::jsonb) RETURNING id''',cid,
            json.dumps({'stage':'preliminary','format':'groups','match_rules':spec['group_rules']}))
        entry_map={e['player_id']:e['id'] for e in entries};count=0
        for ix,ids in enumerate(spec['groups']):
            # A..Z, AA.. for unusually large events.
            label='';j=ix
            while True:
                label=chr(65+j%26)+label;j=j//26-1
                if j<0:break
            gid=await db.fetchval(f'''INSERT INTO {SCHEMA}.groups(phase_id,name,sort_order)
                VALUES($1,$2,$3) RETURNING id''',phase,'Gruppe '+label,ix+1)
            for seed,pid in enumerate(ids):
                await db.execute(f'INSERT INTO {SCHEMA}.group_members(group_id,entry_id,seed) VALUES($1,$2,$3)',gid,entry_map[pid],seed+1)
            for rnd,p1,p2 in round_robin(ids,spec['double_round']):
                await db.execute(f'''INSERT INTO {SCHEMA}.matches(competition_id,phase_id,group_id,round_number,player1_id,player2_id,rules)
                    VALUES($1,$2,$3,$4,$5,$6,$7::jsonb)''',cid,phase,gid,rnd,p1,p2,json.dumps(spec['group_rules']))
                count+=1
    return response({'created':count,'group_count':spec['group_count'],'phase_id':str(phase),'ready':True},201)


async def choose_wildcards(req):
    """Admin decision only for extra qualifying spots; records choice before creating follow rounds."""
    account=await actor(req);cid=uid(req.match_info['cid']);data=await body(req)
    async with pool(req).acquire() as db:
      async with db.transaction():
        await require_manager(db,account,cid)
        c=await db.fetchrow(f'SELECT kind,rules FROM {SCHEMA}.competitions WHERE id=$1 FOR UPDATE',cid)
        cfg=as_json(c['rules']) if c else {}
        if not cfg.get('guided_setup') or not cfg.get('best_third_count'):
            raise web.HTTPConflict(text='Keine Qualifikationsentscheidung nötig')
        if await db.fetchval(f'SELECT EXISTS(SELECT 1 FROM {SCHEMA}.phases WHERE competition_id=$1 AND phase_order>1)',cid):
            raise web.HTTPConflict(text='Folgerunden sind bereits erzeugt')
        ids=[uid(x) for x in data.get('player_ids',[])]
        if len(ids)!=int(cfg['best_third_count']) or len(ids)!=len(set(ids)):
            raise web.HTTPBadRequest(text='Bitte genau die erforderliche Anzahl Qualifikanten wählen')
        cfg['best_third_manual_ids']=[str(x) for x in ids]
        await db.execute(f'UPDATE {SCHEMA}.competitions SET rules=$2::jsonb WHERE id=$1',cid,json.dumps(cfg))
    from .tournament_automation import progress
    await progress(req,cid)
    return response({'selected':len(ids),'advanced':True})
