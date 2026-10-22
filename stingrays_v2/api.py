"""Stingrays v2, standalone under /dart/v2. Deliberately does not modify the legacy routes.

Requires STINGRAYS_DATABASE_URL and the pre-provisioned stingrays_app schema.
Uses short transactions, action-only writes and no background polling/WebSockets.
"""
from __future__ import annotations
import asyncio,csv,io,json,os,secrets
from datetime import datetime,timedelta,timezone
from pathlib import Path
from uuid import UUID
from decimal import Decimal
from aiohttp import web
from .rules import KINDS,elo_change,mode_rules,round_robin,rank_rows,bracket_pairs
from .security import hash_password,verify_password,token_pair,token_digest
from dart_engine import Match,Rules,Visit

HERE=Path(__file__).resolve().parent
COOKIE='stingrays_v2_session'
SCHEMA='stingrays_app'

def uid(raw):
    try:return UUID(str(raw))
    except (TypeError,ValueError,AttributeError):raise web.HTTPBadRequest(text='Ungültige ID')

def as_json(value):
    if isinstance(value,str):return json.loads(value)
    return value or {}

def serialize(value):
    if isinstance(value,UUID):return str(value)
    if isinstance(value,Decimal):return float(value)
    if isinstance(value,datetime):return value.isoformat()
    if hasattr(value,'items'):return dict(value)
    raise TypeError(type(value).__name__)

def response(obj,status=200):return web.json_response(obj,status=status,dumps=lambda o:json.dumps(o,default=serialize,ensure_ascii=False))

def require_same_origin(req):
    origin=req.headers.get('Origin')
    if origin and origin not in (f'{req.scheme}://{req.host}',f'https://{req.host}'):
        raise web.HTTPForbidden(text='Ungültiger Origin')
    if req.method not in ('GET','HEAD','OPTIONS'):
        target=req.headers.get('Sec-Fetch-Site','')
        if target=='cross-site':raise web.HTTPForbidden(text='Cross-Site-Zugriff gesperrt')

async def body(req):
    require_same_origin(req)
    if (req.content_length or 0)>1_000_000:raise web.HTTPRequestEntityTooLarge(max_size=1_000_000,actual_size=req.content_length)
    try:
        data=await req.json()
        if not isinstance(data,dict):raise ValueError()
        return data
    except (ValueError,TypeError,json.JSONDecodeError):raise web.HTTPBadRequest(text='JSON-Objekt erwartet')

def pool(req):
    value=req.app.get('stingrays_pool')
    if value is None:raise web.HTTPServiceUnavailable(text='Neon-Verbindung nicht konfiguriert')
    return value

async def actor(req,minimum=None,allow_change=False):
    require_same_origin(req)
    token=req.cookies.get(COOKIE,'')
    if not token:raise web.HTTPUnauthorized(text='Bitte anmelden')
    async with pool(req).acquire() as db:
        a=await db.fetchrow(f'''SELECT a.id,a.player_id,a.username,a.role,a.must_change_password,a.is_enabled
          FROM {SCHEMA}.sessions s JOIN {SCHEMA}.accounts a ON a.id=s.account_id
          WHERE s.token_hash=$1 AND s.revoked_at IS NULL AND s.expires_at>now()''',token_digest(token))
    if not a or not a['is_enabled']:raise web.HTTPUnauthorized(text='Sitzung ungültig')
    if a['must_change_password'] and not allow_change:raise web.HTTPForbidden(text='Passwortwechsel erforderlich')
    if minimum=='admin' and a['role']!='admin':raise web.HTTPForbidden(text='Nur Administratoren')
    if minimum=='tournament' and a['role'] not in ('admin','tournament'):raise web.HTTPForbidden(text='Nur Turnierleitung')
    return a

async def health(req):
    try:
        async with pool(req).acquire() as db:
            count=await db.fetchval(f'SELECT count(*) FROM {SCHEMA}.boards')
        return response({'status':'ok','boards':count,'database':'connected'})
    except Exception:return response({'status':'unavailable'},503)

async def spa(req):
    return web.FileResponse(HERE/'index.html',headers={'Cache-Control':'no-store'})

async def assets(req):
    which=req.match_info['filename']
    if which not in ('app.js','style.css','legacy_bridge.js','scorer_theme.css','brand.png'):raise web.HTTPNotFound()
    return web.FileResponse(HERE/which,headers={'Cache-Control':'no-store'})

async def legacy_scorer_page(req):
    await actor(req)
    from dart_render_preview import ROOT
    html=(ROOT/'dart_ui'/'index.html').read_text(encoding='utf-8')
    html=html.replace("api('state').then(s=>{S=s;if(S.kind==='x01')showMatch();else if(S.kind==='sau')showSau();else screen('menuView')}).catch(()=>screen('loginView'));",'')
    html=html.replace('</head>', '<link rel="stylesheet" href="/dart/v2/assets/scorer_theme.css"></head>')
    html=html.replace('</body>', '<script src="/dart/v2/assets/legacy_bridge.js"></script></body>')
    return web.Response(text=html,content_type='text/html',headers={'Cache-Control':'no-store'})

async def bootstrap(req):
    d=await body(req)
    expected=os.environ.get('DART_ADMIN_PIN','')
    if len(expected)<10 or not secrets.compare_digest(str(d.get('bootstrap_pin','')),expected):
        await asyncio.sleep(.4);raise web.HTTPForbidden(text='Ungültiger Administrator-PIN')
    name=str(d.get('username','')).strip()
    if not 3<=len(name)<=80:raise web.HTTPBadRequest(text='Benutzername: 3–80 Zeichen')
    try:pw=hash_password(str(d.get('password','')))
    except ValueError as e:raise web.HTTPBadRequest(text=str(e))
    async with pool(req).acquire() as db:
        async with db.transaction():
            # Serialize competing bootstrap calls using one transaction-scoped advisory lock.
            await db.execute('SELECT pg_advisory_xact_lock(778191922)')
            if await db.fetchval(f'SELECT EXISTS(SELECT 1 FROM {SCHEMA}.accounts)'):
                raise web.HTTPConflict(text='Admin-Konto bereits vorhanden')
            p=await db.fetchval(f"INSERT INTO {SCHEMA}.players(display_name,is_member) VALUES($1,true) RETURNING id",name)
            a=await db.fetchval(f'''INSERT INTO {SCHEMA}.accounts(player_id,username,password_hash,role,must_change_password)
              VALUES($1,$2,$3,'admin',false) RETURNING id''',p,name,pw)
            await db.execute(f"INSERT INTO {SCHEMA}.audit_log(actor_id,action,target_type,target_id) VALUES($1,'bootstrap','account',$2)",a,str(a))
    return response({'created':True},201)

async def login(req):
    d=await body(req)
    name=str(d.get('username','')).strip()
    async with pool(req).acquire() as db:
        a=await db.fetchrow(f'SELECT * FROM {SCHEMA}.accounts WHERE lower(username)=lower($1)',name)
        ok=a and a['is_enabled'] and verify_password(str(d.get('password','')),a['password_hash'])
        if not ok:
            await asyncio.sleep(.45);raise web.HTTPUnauthorized(text='Anmeldung fehlgeschlagen')
        raw,th=token_pair()
        await db.execute(f'''INSERT INTO {SCHEMA}.sessions(account_id,token_hash,expires_at)
              VALUES($1,$2,now()+interval '12 hours')''',a['id'],th)
    result=response({'username':a['username'],'role':a['role'],'must_change_password':a['must_change_password']})
    result.set_cookie(COOKIE,raw,httponly=True,secure=True,samesite='Strict',max_age=43200,path='/dart/v2')
    return result

async def logout(req):
    await body(req)
    token=req.cookies.get(COOKIE,'')
    if token:
        async with pool(req).acquire() as db:
            await db.execute(f'UPDATE {SCHEMA}.sessions SET revoked_at=now() WHERE token_hash=$1',token_digest(token))
    result=response({'ok':True});result.del_cookie(COOKIE,path='/dart/v2');return result

async def me(req):
    a=await actor(req,allow_change=True)
    return response(dict(a))

async def password(req):
    a=await actor(req,allow_change=True);d=await body(req)
    try:pw=hash_password(str(d.get('new_password','')))
    except ValueError as e:raise web.HTTPBadRequest(text=str(e))
    async with pool(req).acquire() as db:
        rec=await db.fetchval(f'SELECT password_hash FROM {SCHEMA}.accounts WHERE id=$1',a['id'])
        if not verify_password(str(d.get('old_password','')),rec):raise web.HTTPForbidden(text='Aktuelles Passwort ungültig')
        async with db.transaction():
            await db.execute(f'UPDATE {SCHEMA}.accounts SET password_hash=$2,must_change_password=false WHERE id=$1',a['id'],pw)
            await db.execute(f'UPDATE {SCHEMA}.sessions SET revoked_at=now() WHERE account_id=$1 AND token_hash<>$2',a['id'],token_digest(req.cookies.get(COOKIE,'')))
    return response({'ok':True})

async def members(req):
    await actor(req)
    async with pool(req).acquire() as db:
        rows=await db.fetch(f'''SELECT p.id,p.legacy_profile_id,p.display_name,p.is_active,p.is_member,
          a.username,a.role,a.is_enabled FROM {SCHEMA}.players p LEFT JOIN {SCHEMA}.accounts a ON a.player_id=p.id
          ORDER BY p.display_name''')
    return response(list(map(dict,rows)))

async def create_member(req):
    a=await actor(req,'admin');d=await body(req)
    name=str(d.get('display_name','')).strip();legacy=str(d.get('legacy_profile_id','')).strip() or None
    if not name or len(name)>120:raise web.HTTPBadRequest(text='Spielername erforderlich')
    async with pool(req).acquire() as db:
        try:
            p=await db.fetchrow(f'''INSERT INTO {SCHEMA}.players(display_name,legacy_profile_id,is_member,is_active)
             VALUES($1,$2,$3,true) RETURNING *''',name,legacy,bool(d.get('is_member',True)))
        except Exception as exc:
            if getattr(exc,'sqlstate',None)=='23505':raise web.HTTPConflict(text='Profil-ID bereits vorhanden')
            raise
    return response(dict(p),201)

async def create_account(req):
    a=await actor(req,'admin');d=await body(req)
    role=str(d.get('role','member'))
    if role not in ('member','admin','tournament'):raise web.HTTPBadRequest(text='Ungültige Rolle')
    name=str(d.get('username','')).strip()
    if not 3<=len(name)<=80:raise web.HTTPBadRequest(text='Benutzername: 3–80 Zeichen')
    try:pw=hash_password(str(d.get('initial_password','')))
    except ValueError as e:raise web.HTTPBadRequest(text=str(e))
    pid=uid(d['player_id']) if d.get('player_id') else None
    async with pool(req).acquire() as db:
        try:
            target=await db.fetchval(f'''INSERT INTO {SCHEMA}.accounts(player_id,username,password_hash,role,must_change_password,is_enabled)
              VALUES($1,$2,$3,$4,true,true) RETURNING id''',pid,name,pw,role)
        except Exception as exc:
            if getattr(exc,'sqlstate',None)=='23505':raise web.HTTPConflict(text='Konto oder Profil bereits vergeben')
            raise
        await db.execute(f"INSERT INTO {SCHEMA}.audit_log(actor_id,action,target_type,target_id) VALUES($1,'create_account','account',$2)",a['id'],str(target))
    return response({'id':target,'username':name,'role':role},201)

async def reset_account(req):
    a=await actor(req,'admin');d=await body(req);target=uid(req.match_info['aid'])
    async with pool(req).acquire() as db:
        if 'is_enabled' in d:
            if a['id']==target and not d['is_enabled']:raise web.HTTPBadRequest(text='Eigenes Admin-Konto nicht deaktivieren')
            await db.execute(f'UPDATE {SCHEMA}.accounts SET is_enabled=$2 WHERE id=$1',target,bool(d['is_enabled']))
            await db.execute(f'UPDATE {SCHEMA}.sessions SET revoked_at=now() WHERE account_id=$1',target)
        if 'initial_password' in d:
            try:pw=hash_password(str(d['initial_password']))
            except ValueError as e:raise web.HTTPBadRequest(text=str(e))
            await db.execute(f'UPDATE {SCHEMA}.accounts SET password_hash=$2,must_change_password=true WHERE id=$1',target,pw)
            await db.execute(f'UPDATE {SCHEMA}.sessions SET revoked_at=now() WHERE account_id=$1',target)
    return response({'ok':True})

async def board_list(req):
    await actor(req)
    async with pool(req).acquire() as db:
        rows=await db.fetch(f'''SELECT b.id,b.label,b.enabled,m.id AS match_id,c.title AS competition
            FROM {SCHEMA}.boards b LEFT JOIN {SCHEMA}.matches m ON m.board_id=b.id AND m.status='running'
            LEFT JOIN {SCHEMA}.competitions c ON c.id=m.competition_id ORDER BY b.id''')
    return response(list(map(dict,rows)))

async def edit_board(req):
    await actor(req,'admin');d=await body(req);bid=int(req.match_info['bid'])
    if not 1<=bid<=22:raise web.HTTPBadRequest(text='Board 1–22')
    async with pool(req).acquire() as db:
        await db.execute(f'''UPDATE {SCHEMA}.boards SET label=COALESCE($2,label),enabled=COALESCE($3,enabled) WHERE id=$1''',
                         bid,str(d['label'])[:100] if 'label' in d else None,d.get('enabled'))
    return response({'ok':True})

async def allowed_to_manage(db, account, competition_id):
    if account['role']=='admin':return True
    return bool(await db.fetchval(f'''SELECT 1 FROM {SCHEMA}.competitions
        WHERE id=$1 AND kind='training_tournament' AND created_by=$2 AND deleted_at IS NULL''',
        competition_id,account['id']))

async def require_manager(db, account, competition_id):
    if not await allowed_to_manage(db, account, competition_id):
        raise web.HTTPForbidden(text='Nur Vereinsadministratoren bzw. Ersteller eigener Trainingsturniere')

async def competition_list(req):
    await actor(req)
    async with pool(req).acquire() as db:
        rows=await db.fetch(f'''SELECT c.id,c.title,c.kind,c.status,c.starts_at,c.ends_at,c.rules,c.created_by,
            (SELECT count(*) FROM {SCHEMA}.entries e WHERE e.competition_id=c.id) AS players
            FROM {SCHEMA}.competitions c WHERE c.deleted_at IS NULL ORDER BY c.created_at DESC''')
    return response(list(map(dict,rows)))

async def create_competition(req):
    a=await actor(req);d=await body(req)
    kind=str(d.get('kind',''))
    if kind not in KINDS:raise web.HTTPBadRequest(text='Unbekannter Wettbewerb')
    if kind!='training_tournament' and a['role']!='admin':raise web.HTTPForbidden(text='Wettbewerb nur durch Administratoren')
    title=str(d.get('title','')).strip()
    if not title or len(title)>150:raise web.HTTPBadRequest(text='Titel erforderlich')
    if kind=='ladder' and (not d.get('starts_at') or not d.get('ends_at')):
        raise web.HTTPBadRequest(text='Ladder benötigt Beginn und Ende')
    try:
        start=datetime.fromisoformat(d['starts_at']) if d.get('starts_at') else None
        end=datetime.fromisoformat(d['ends_at']) if d.get('ends_at') else None
        if start and not start.tzinfo:start=start.replace(tzinfo=timezone.utc)
        if end and not end.tzinfo:end=end.replace(tzinfo=timezone.utc)
    except ValueError:raise web.HTTPBadRequest(text='Datum im ISO-Format erwartet')
    if start and end and end<=start:raise web.HTTPBadRequest(text='Ende muss nach dem Start liegen')
    rules=d.get('rules') or {}
    if not isinstance(rules,dict):raise web.HTTPBadRequest(text='Regeln als Objekt erwartet')
    if kind=='ladder':rules.update(k_factor=64,initial_elo=1000,rematch_cooldown_days=7)
    async with pool(req).acquire() as db:
        async with db.transaction():
            c=await db.fetchrow(f'''INSERT INTO {SCHEMA}.competitions(title,kind,status,starts_at,ends_at,rules,created_by)
                VALUES($1,$2,$7,$3,$4,$5::jsonb,$6) RETURNING id,title,kind,status''',
                title,kind,start,end,json.dumps(rules),a['id'],'active' if kind in ('ladder','training_tournament') else 'draft')
            if kind in ('ladder','training_tournament'):
                await db.execute(f'''INSERT INTO {SCHEMA}.phases(competition_id,name,kind,phase_order,status)
                  VALUES($1,$2,$3,1,'open')''',c['id'],
                  'Ladder-Saison' if kind=='ladder' else 'Training',
                  'ladder' if kind=='ladder' else 'groups')
            if kind=='training_tournament' and a['player_id']:
                await db.execute(f'''INSERT INTO {SCHEMA}.entries(competition_id,player_id)
                    VALUES($1,$2) ON CONFLICT DO NOTHING''',c['id'],a['player_id'])
            if kind=='ladder':
                # Enroll every active club member, independent of whether they own a login.
                await db.execute(f'''INSERT INTO {SCHEMA}.entries(competition_id,player_id)
                    SELECT $1,p.id FROM {SCHEMA}.players p
                    WHERE p.is_member IS TRUE AND p.is_active IS TRUE
                    ON CONFLICT(competition_id,player_id) DO NOTHING''',c['id'])
                # Keep eligible but not-yet-playing members at initial Elo, with played=0.
                # The rankings endpoint deliberately filters played>0.
                await db.execute(f'''INSERT INTO {SCHEMA}.ladder_ratings(competition_id,player_id)
                    SELECT $1,e.player_id FROM {SCHEMA}.entries e
                    WHERE e.competition_id=$1
                    ON CONFLICT DO NOTHING''',c['id'])
                enrolled=await db.fetchval(f'''SELECT count(*) FROM {SCHEMA}.entries
                    WHERE competition_id=$1''',c['id'])
    result=dict(c)
    if kind=='ladder':result['enrolled_members']=enrolled
    return response(result,201)

async def competition_detail(req):
    await actor(req);cid=uid(req.match_info['cid'])
    async with pool(req).acquire() as db:
        comp=await db.fetchrow(f'SELECT * FROM {SCHEMA}.competitions WHERE id=$1 AND deleted_at IS NULL',cid)
        if not comp:raise web.HTTPNotFound()
        phases=await db.fetch(f'SELECT * FROM {SCHEMA}.phases WHERE competition_id=$1 ORDER BY phase_order',cid)
        groups=await db.fetch(f'''SELECT g.id,g.name,g.phase_id,g.sort_order,g.tie_breakers FROM {SCHEMA}.groups g
          JOIN {SCHEMA}.phases p ON p.id=g.phase_id WHERE p.competition_id=$1 ORDER BY g.sort_order''',cid)
        entries=await db.fetch(f'''SELECT e.id AS entry_id,p.id AS player_id,p.display_name,e.status,e.seed FROM {SCHEMA}.entries e
          JOIN {SCHEMA}.players p ON p.id=e.player_id WHERE e.competition_id=$1 ORDER BY p.display_name''',cid)
        membership=await db.fetch(f'''SELECT gm.group_id,gm.entry_id FROM {SCHEMA}.group_members gm
           JOIN {SCHEMA}.groups g ON g.id=gm.group_id JOIN {SCHEMA}.phases p ON p.id=g.phase_id
           WHERE p.competition_id=$1''',cid)
        matches=await db.fetch(f'''SELECT m.id,m.phase_id,m.group_id,m.round_number,m.player1_id,m.player2_id,
            m.status,m.source,m.legs1,m.legs2,m.sets1,m.sets2,m.board_id,m.rules,m.finished_at
           FROM {SCHEMA}.matches m WHERE m.competition_id=$1 ORDER BY m.created_at''',cid)
    return response({'competition':dict(comp),'phases':list(map(dict,phases)),'groups':list(map(dict,groups)),
                     'entries':list(map(dict,entries)),'memberships':list(map(dict,membership)),'matches':list(map(dict,matches))})

async def add_entries(req):
    a=await actor(req);d=await body(req);cid=uid(req.match_info['cid']);ids=d.get('player_ids',[])
    if not isinstance(ids,list) or len(ids)>500:raise web.HTTPBadRequest(text='Ungültige Teilnehmer')
    async with pool(req).acquire() as db:
        async with db.transaction():
            await require_manager(db,a,cid)
            for pid in ids:
                await db.execute(f'''INSERT INTO {SCHEMA}.entries(competition_id,player_id)
                    VALUES($1,$2) ON CONFLICT(competition_id,player_id) DO NOTHING''',cid,uid(pid))
    return response({'added':len(ids)})

async def create_phase(req):
    a=await actor(req);d=await body(req);cid=uid(req.match_info['cid'])
    kind=str(d.get('kind',''))
    if kind not in ('league','groups','knockout','ladder'):raise web.HTTPBadRequest(text='Ungültige Phase')
    async with pool(req).acquire() as db:
        await require_manager(db,a,cid)
        if await db.fetchval(f"SELECT kind='ladder' FROM {SCHEMA}.competitions WHERE id=$1",cid):raise web.HTTPConflict(text='Ladder benötigt keine Gruppenphase')
        n=await db.fetchval(f'SELECT coalesce(max(phase_order),0)+1 FROM {SCHEMA}.phases WHERE competition_id=$1',cid)
        row=await db.fetchrow(f'''INSERT INTO {SCHEMA}.phases(competition_id,name,kind,phase_order,status,rules)
          VALUES($1,$2,$3,$4,'open',$5::jsonb) RETURNING *''',cid,str(d.get('name',kind))[:120],kind,n,json.dumps(d.get('rules') or {}))
    return response(dict(row),201)

async def create_group(req):
    a=await actor(req);d=await body(req);pid=uid(req.match_info['pid'])
    async with pool(req).acquire() as db:
        cid=await db.fetchval(f'SELECT competition_id FROM {SCHEMA}.phases WHERE id=$1',pid)
        if not cid:raise web.HTTPNotFound()
        await require_manager(db,a,cid)
        n=await db.fetchval(f'SELECT coalesce(max(sort_order),0)+1 FROM {SCHEMA}.groups WHERE phase_id=$1',pid)
        row=await db.fetchrow(f'''INSERT INTO {SCHEMA}.groups(phase_id,name,sort_order)
             VALUES($1,$2,$3) RETURNING *''',pid,str(d.get('name','Gruppe '+str(n)))[:120],n)
    return response(dict(row),201)

async def assign_group(req):
    a=await actor(req);d=await body(req);gid=uid(req.match_info['gid']);ids=d.get('entry_ids',[])
    if not isinstance(ids,list):raise web.HTTPBadRequest()
    async with pool(req).acquire() as db:
        group=await db.fetchrow(f'''SELECT g.phase_id,p.competition_id,p.status FROM {SCHEMA}.groups g
          JOIN {SCHEMA}.phases p ON p.id=g.phase_id WHERE g.id=$1''',gid)
        if not group:raise web.HTTPNotFound()
        await require_manager(db,a,group['competition_id'])
        if group['status']=='closed':raise web.HTTPConflict(text='Phase geschlossen')
        if await db.fetchval(f'''SELECT EXISTS(SELECT 1 FROM {SCHEMA}.matches WHERE group_id=$1 AND status IN ('running','finished'))''',gid):
            raise web.HTTPConflict(text='Gruppe hat bereits gestartete oder abgeschlossene Spiele')
        async with db.transaction():
            await db.execute(f'DELETE FROM {SCHEMA}.group_members WHERE group_id=$1',gid)
            for e in ids:
                eid=uid(e)
                owner=await db.fetchval(f'SELECT competition_id FROM {SCHEMA}.entries WHERE id=$1',eid)
                if owner!=group['competition_id']:raise web.HTTPBadRequest(text='Teilnehmer gehört nicht zum Wettbewerb')
                await db.execute(f'DELETE FROM {SCHEMA}.group_members WHERE entry_id=$1 AND group_id IN (SELECT g.id FROM {SCHEMA}.groups g WHERE g.phase_id=$2)',eid,group['phase_id'])
                await db.execute(f'INSERT INTO {SCHEMA}.group_members(group_id,entry_id) VALUES($1,$2)',gid,eid)
    return response({'assigned':len(ids)})

async def generate_rounds(req):
    a=await actor(req);d=await body(req);gid=uid(req.match_info['gid'])
    async with pool(req).acquire() as db:
        async with db.transaction():
            g=await db.fetchrow(f'''SELECT g.phase_id,p.competition_id,c.kind,p.kind AS phase_kind,p.status
               FROM {SCHEMA}.groups g JOIN {SCHEMA}.phases p ON p.id=g.phase_id
               JOIN {SCHEMA}.competitions c ON c.id=p.competition_id WHERE g.id=$1 FOR UPDATE OF g''',gid)
            if not g:raise web.HTTPNotFound()
            await require_manager(db,a,g['competition_id'])
            if g['status']=='closed':raise web.HTTPConflict(text='Phase geschlossen')
            if await db.fetchval(f'SELECT EXISTS(SELECT 1 FROM {SCHEMA}.matches WHERE group_id=$1)',gid):
                raise web.HTTPConflict(text='Spielplan bereits vorhanden')
            ids=await db.fetch(f'''SELECT e.player_id FROM {SCHEMA}.group_members gm
               JOIN {SCHEMA}.entries e ON e.id=gm.entry_id WHERE gm.group_id=$1 ORDER BY gm.seed NULLS LAST,e.seed NULLS LAST, e.id''',gid)
            fixture=round_robin([r['player_id'] for r in ids],bool(d.get('double_round',False)))
            rules=mode_rules(g['kind'],g['phase_kind'],overrides=d.get('rules') or {})
            for rnd,x,y in fixture:
                await db.execute(f'''INSERT INTO {SCHEMA}.matches(competition_id,phase_id,group_id,round_number,player1_id,player2_id,rules)
                 VALUES($1,$2,$3,$4,$5,$6,$7::jsonb)''',g['competition_id'],g['phase_id'],gid,rnd,x,y,json.dumps(rules))
    return response({'created':len(fixture)},201)

async def create_match(req):
    a=await actor(req);d=await body(req);cid=uid(req.match_info['cid'])
    async with pool(req).acquire() as db:
        c=await db.fetchrow(f'SELECT kind,status,starts_at,ends_at,created_by FROM {SCHEMA}.competitions WHERE id=$1 AND deleted_at IS NULL',cid)
        if not c:raise web.HTTPNotFound()
        if c['kind'] not in ('ladder','training_tournament') and a['role']!='admin':raise web.HTTPForbidden(text='Nur Administratoren legen Vereinsbegegnungen an')
        if c['kind']=='training_tournament' and a['role']!='admin' and c['created_by']!=a['id']:
            raise web.HTTPForbidden(text='Nur eigene Trainingsturniere bearbeiten')
        if c['kind']=='ladder' and c['status']!='active':raise web.HTTPConflict(text='Ladder nicht aktiv')
        ids=[uid(d.get('player1_id')),uid(d.get('player2_id'))]
        if ids[0]==ids[1]:raise web.HTTPBadRequest(text='Verschiedene Spieler erforderlich')
        if c['kind']=='training_tournament' and a['role']=='member' and a['player_id'] not in ids:raise web.HTTPForbidden(text='Nur eigene Trainingsspiele starten')
        if c['kind']=='ladder':
            if c['starts_at'] and datetime.now(timezone.utc)<c['starts_at'] or c['ends_at'] and datetime.now(timezone.utc)>=c['ends_at']:
                raise web.HTTPConflict(text='Außerhalb des Ladder-Zeitraums')
            # Player account can only initiate games in which they participate.
            if a['role']=='member' and a['player_id'] not in ids:raise web.HTTPForbidden(text='Nicht deine Begegnung')
        for pid in ids:
            if not await db.fetchval(f'SELECT EXISTS(SELECT 1 FROM {SCHEMA}.entries WHERE competition_id=$1 AND player_id=$2)',cid,pid):
                raise web.HTTPBadRequest(text='Spieler nicht im Wettbewerb')
        phase=await db.fetchval(f'''SELECT id FROM {SCHEMA}.phases WHERE competition_id=$1 AND kind=$2 ORDER BY phase_order LIMIT 1''',cid,'ladder' if c['kind']=='ladder' else 'groups' if c['kind']=='training_tournament' else 'league')
        if not phase and c['kind']=='ladder':
            phase=await db.fetchval(f'''INSERT INTO {SCHEMA}.phases(competition_id,name,kind,phase_order,status)
                VALUES($1,'Ladder-Saison','ladder',1,'open') ON CONFLICT(competition_id,phase_order)
                DO UPDATE SET kind='ladder' RETURNING id''',cid)
        if not phase:raise web.HTTPConflict(text='Phase fehlt')
        if c['kind']=='ladder':
            recent=await db.fetchval(f'''SELECT EXISTS(SELECT 1 FROM {SCHEMA}.matches WHERE competition_id=$1
                  AND status='finished' AND finished_at>now()-interval '7 days'
                  AND ((player1_id=$2 AND player2_id=$3) OR (player1_id=$3 AND player2_id=$2)))''',cid,*ids)
            if recent:raise web.HTTPConflict(text='Diese Paarung darf erst nach 7 Tagen erneut gewertet werden')
        user_rules=d.get('rules') or {}
        if not isinstance(user_rules,dict):raise web.HTTPBadRequest(text='Ungültige Spielregeln')
        try:rules=mode_rules(c['kind'],'ladder' if c['kind']=='ladder' else 'groups',overrides=user_rules)
        except (ValueError,TypeError,KeyError) as exc:raise web.HTTPBadRequest(text=str(exc))
        if c['kind']=='ladder':
            if rules['mode']=='legs' and int(rules['max_legs'])<5:
                raise web.HTTPBadRequest(text='Ladder: mindestens Best of 5 Legs')
            rules['allow_draw']=rules['mode']=='legs' and int(rules['max_legs'])%2==0
        row=await db.fetchrow(f'''INSERT INTO {SCHEMA}.matches(competition_id,phase_id,player1_id,player2_id,rules)
           VALUES($1,$2,$3,$4,$5::jsonb) RETURNING id''',cid,phase,*ids,json.dumps(rules))
    return response({'id':row['id']},201)

async def standings(req):
    await actor(req);cid=uid(req.match_info['cid'])
    async with pool(req).acquire() as db:
        c=await db.fetchrow(f'SELECT kind FROM {SCHEMA}.competitions WHERE id=$1',cid)
        if not c:raise web.HTTPNotFound()
        if c['kind']=='ladder':
            rows=await db.fetch(f'''SELECT r.*,p.display_name,round(100.0*r.wins/nullif(r.played,0),1) AS win_percent
                 FROM {SCHEMA}.ladder_ratings r JOIN {SCHEMA}.players p ON p.id=r.player_id
                 WHERE r.competition_id=$1 AND r.played>0 ORDER BY r.elo DESC,r.played DESC''',cid)
            # Averages are calculated from completed ladder matches only.
            # Opponent ELO uses the recorded pre-match rating, not today's ELO.
            events=await db.fetch(f'''SELECT le.match_id,le.player_id,le.elo_before,
                 m.player1_id,m.player2_id,m.state,m.source
                 FROM {SCHEMA}.ladder_events le
                 JOIN {SCHEMA}.matches m ON m.id=le.match_id
                 WHERE le.competition_id=$1 AND m.status='finished' ''',cid)
            by_match={}
            for e in events:by_match.setdefault(e['match_id'],[]).append(e)
            totals={r['player_id']:{'opponent_elo':[],'own_scores':0,'own_darts':0,
                 'opponent_scores':0,'opponent_darts':0} for r in rows}
            for egroup in by_match.values():
                if len(egroup)!=2:continue
                for e in egroup:
                    own=e['player_id'];op=next(x for x in egroup if x['player_id']!=own)
                    if own not in totals:continue
                    t=totals[own];t['opponent_elo'].append(float(op['elo_before']))
                    if e['source']!='scorer':continue
                    raw=as_json(e['state'])
                    ix=0 if e['player1_id']==own else 1
                    for visit in raw.get('visits',[]):
                        if visit.get('player')==ix:
                            t['own_scores']+=0 if visit.get('bust') else int(visit.get('score',0))
                            t['own_darts']+=int(visit.get('darts',3))
                        else:
                            t['opponent_scores']+=0 if visit.get('bust') else int(visit.get('score',0))
                            t['opponent_darts']+=int(visit.get('darts',3))
            answer=[]
            for r in rows:
                item=dict(r);t=totals[r['player_id']];values=t['opponent_elo']
                item['average_opponent_elo']=round(sum(values)/len(values),1) if values else None
                item['own_average']=round(3*t['own_scores']/t['own_darts'],2) if t['own_darts'] else None
                item['opponent_average']=round(3*t['opponent_scores']/t['opponent_darts'],2) if t['opponent_darts'] else None
                answer.append(item)
            return response(answer)
        gid=uid(req.query['group_id']) if req.query.get('group_id') else None
        if gid:
            entries=await db.fetch(f'''SELECT e.player_id,p.display_name FROM {SCHEMA}.group_members gm
              JOIN {SCHEMA}.entries e ON e.id=gm.entry_id JOIN {SCHEMA}.players p ON p.id=e.player_id
              JOIN {SCHEMA}.groups g ON g.id=gm.group_id JOIN {SCHEMA}.phases ph ON ph.id=g.phase_id
              WHERE gm.group_id=$1 AND ph.competition_id=$2''',gid,cid)
        else:
            entries=await db.fetch(f'''SELECT e.player_id,p.display_name FROM {SCHEMA}.entries e
                  JOIN {SCHEMA}.players p ON p.id=e.player_id WHERE e.competition_id=$1''',cid)
        ms=await db.fetch(f'''SELECT player1_id,player2_id,status,legs1,legs2,sets1,sets2 FROM {SCHEMA}.matches
              WHERE competition_id=$1 AND ($2::uuid IS NULL OR group_id=$2)''',cid,gid)
    ranks=rank_rows([dict(m) for m in ms],[r['player_id'] for r in entries]);names={r['player_id']:r['display_name'] for r in entries}
    for i,r in enumerate(ranks,1):r.update(rank=i,name=names.get(r['player_id']))
    return response(ranks)

async def match_state(req):
    a=await actor(req);mid=uid(req.match_info['mid'])
    async with pool(req).acquire() as db:
        m=await db.fetchrow(f'''SELECT m.*,p1.display_name AS player1,p2.display_name AS player2,c.kind,c.status AS competition_status
          FROM {SCHEMA}.matches m JOIN {SCHEMA}.players p1 ON p1.id=m.player1_id
          JOIN {SCHEMA}.players p2 ON p2.id=m.player2_id
          JOIN {SCHEMA}.competitions c ON c.id=m.competition_id WHERE m.id=$1 AND c.deleted_at IS NULL''',mid)
        if not m:raise web.HTTPNotFound()
        claimed=await db.fetchrow(f'SELECT account_id,lease_until FROM {SCHEMA}.match_claims WHERE match_id=$1',mid)
    item=dict(m);item['summary']=unpack_game(m).summary() if m['status']=='finished' and as_json(m['state']) else None;item['can_score']=a['role'] in ('admin','tournament') or a['player_id'] in (m['player1_id'],m['player2_id'])
    item['claim_active']=bool(claimed and claimed['lease_until']>datetime.now(timezone.utc))
    item['claim_mine']=bool(claimed and claimed['account_id']==a['id'] and item['claim_active'])
    return response(item)

def unpack_game(m):
    raw=as_json(m['state']);rules=as_json(m['rules'])
    if not raw:
        g=Match(Rules(**rules),(m['player1'],m['player2']))
        return g
    # Some earlier V2 starts saved only {current,first_throw}. Merge, never
    # assume a partial JSON state contains the complete scoring engine.
    g=Match(Rules(**{**rules,**raw.get('rules',{})}),tuple(raw.get('names') or (m['player1'],m['player2'])))
    for k in ('remaining','legs','sets','current','first_throw','leg_number','done'):
        if k in raw:setattr(g,k,raw[k])
    g.visits=[Visit(**v) for v in raw.get('visits',[])]
    return g

def pack_game(g):
    from dataclasses import asdict
    return {'rules':asdict(g.rules),'names':list(g.names),'remaining':list(g.remaining),'legs':list(g.legs),
            'sets':list(g.sets),'current':g.current,'first_throw':g.first_throw,'leg_number':g.leg_number,
            'done':g.done,'visits':[asdict(v) for v in g.visits]}

async def start_match(req):
    a=await actor(req);d=await body(req);mid=uid(req.match_info['mid']);board=d.get('board_id')
    if board is not None:board=int(board)
    if board is not None and not 1<=board<=22:raise web.HTTPBadRequest(text='Board 1–22')
    device=str(d.get('device_id',''))[:100] or token_digest(req.cookies.get(COOKIE,''))[:18]
    async with pool(req).acquire() as db:
      async with db.transaction():
        m=await db.fetchrow(f'''SELECT m.*,p1.display_name AS player1,p2.display_name AS player2,c.kind,c.status AS competition_status,c.ends_at
           FROM {SCHEMA}.matches m JOIN {SCHEMA}.players p1 ON p1.id=m.player1_id
           JOIN {SCHEMA}.players p2 ON p2.id=m.player2_id JOIN {SCHEMA}.competitions c ON c.id=m.competition_id
           WHERE m.id=$1 FOR UPDATE OF m''',mid)
        if not m:raise web.HTTPNotFound()
        if a['role']=='member' and a['player_id'] not in (m['player1_id'],m['player2_id']):
            raise web.HTTPForbidden(text='Nur eigene Begegnungen starten')
        if m['status'] not in ('open','running'):raise web.HTTPConflict(text='Begegnung nicht spielbar')
        if m['competition_status'] in ('archived','finished') or m['ends_at'] and datetime.now(timezone.utc)>=m['ends_at']:
            raise web.HTTPConflict(text='Wettbewerb beendet')
        if board is not None:
            ok=await db.fetchval(f'SELECT enabled FROM {SCHEMA}.boards WHERE id=$1',board)
            if not ok:raise web.HTTPConflict(text='Board deaktiviert')
            conflict=await db.fetchval(f"SELECT id FROM {SCHEMA}.matches WHERE board_id=$1 AND status='running' AND id<>$2",board,mid)
            if conflict:raise web.HTTPConflict(text='Board bereits belegt')
        claim=await db.fetchrow(f'SELECT account_id,token_hash,lease_until FROM {SCHEMA}.match_claims WHERE match_id=$1 FOR UPDATE',mid)
        if claim and claim['lease_until']>datetime.now(timezone.utc) and (claim['account_id']!=a['id'] or claim['token_hash']!=token_digest(req.cookies.get(COOKIE,''))) and a['role']!='admin':
            raise web.HTTPConflict(text='Dieses Match wird bereits von einem anderen Konto bedient')
        await db.execute(f'''INSERT INTO {SCHEMA}.match_claims(match_id,account_id,device_id,token_hash,claimed_at,lease_until)
          VALUES($1,$2,$3,$4,now(),now()+interval '45 minutes') ON CONFLICT(match_id)
          DO UPDATE SET account_id=EXCLUDED.account_id,device_id=EXCLUDED.device_id,token_hash=EXCLUDED.token_hash,
          claimed_at=now(),lease_until=EXCLUDED.lease_until,released_at=NULL''',mid,a['id'],device,token_digest(req.cookies.get(COOKIE,'')))
        state=pack_game(unpack_game(m))
        if not as_json(m['state']):
            starter=int(d.get('starter',0))
            if starter not in (0,1):raise web.HTTPBadRequest(text='Startspieler 0 oder 1')
            state['current']=starter
            state['first_throw']=starter
        await db.execute(f'''UPDATE {SCHEMA}.matches SET status='running',source='scorer',board_id=COALESCE($2,board_id),
           state=CASE WHEN state='{{}}'::jsonb THEN $3::jsonb ELSE state END,
           started_at=COALESCE(started_at,now()) WHERE id=$1''',mid,board,json.dumps(state))
    return response({'ok':True,'state':state,'version':m['state_version']})

async def throw(req):
    a=await actor(req);d=await body(req);mid=uid(req.match_info['mid'])
    async with pool(req).acquire() as db:
      async with db.transaction():
        m=await db.fetchrow(f'''SELECT m.*,p1.display_name AS player1,p2.display_name AS player2,c.kind,c.ends_at
            FROM {SCHEMA}.matches m JOIN {SCHEMA}.players p1 ON p1.id=m.player1_id
            JOIN {SCHEMA}.players p2 ON p2.id=m.player2_id JOIN {SCHEMA}.competitions c ON c.id=m.competition_id
            WHERE m.id=$1 FOR UPDATE OF m''',mid)
        if not m or m['status']!='running':raise web.HTTPConflict(text='Match nicht gestartet')
        if m['ends_at'] and datetime.now(timezone.utc)>=m['ends_at']:raise web.HTTPConflict(text='Saison beendet')
        if a['role']=='member' and a['player_id'] not in (m['player1_id'],m['player2_id']):raise web.HTTPForbidden()
        c=await db.fetchrow(f'SELECT account_id,token_hash,lease_until FROM {SCHEMA}.match_claims WHERE match_id=$1',mid)
        if not c or c['account_id']!=a['id'] or c['token_hash']!=token_digest(req.cookies.get(COOKIE,'')) or c['lease_until']<=datetime.now(timezone.utc):
            raise web.HTTPConflict(text='Match nicht auf diesem Gerät beansprucht; bitte neu starten')
        if m['state_version']!=int(d.get('version',-1)):raise web.HTTPConflict(text='Score wurde inzwischen geändert – bitte neu laden')
        g=unpack_game(m);previous=pack_game(g)
        before=g.remaining[g.current];player=g.current;leg_number=g.leg_number
        try:
            v=g.submit(player,int(d['points']),darts=int(d.get('darts',3)),checkout_attempts=int(d.get('checkout_attempts',0)),
                       checkout=bool(d.get('checkout',False)),bullfinish=bool(d.get('bullfinish',False)))
        except (ValueError,KeyError) as exc:raise web.HTTPBadRequest(text=str(exc))
        current=pack_game(g)
        # One persistent leg per match/leg index; visit numbers are per player and leg.
        leg=await db.fetchrow(f'''INSERT INTO {SCHEMA}.match_legs(match_id,leg_number,starter_id)
          VALUES($1,$2,$3) ON CONFLICT(match_id,leg_number) DO UPDATE SET leg_number=EXCLUDED.leg_number
          RETURNING id''',mid,leg_number+1,m['player1_id'] if (leg_number%2)==0 else m['player2_id'])
        player_id=m['player1_id'] if player==0 else m['player2_id']
        visit_no=sum(1 for old in previous['visits'] if old['leg_index']==leg_number and old['player']==player)+1
        await db.execute(f'''INSERT INTO {SCHEMA}.throws(match_id,leg_id,player_id,visit_number,points,darts,
          remainder_before,remainder_after,is_bust,is_checkout,is_bullfinish)
          VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)''',mid,leg['id'],player_id,visit_no,
          v.score,v.darts,before,0 if v.checkout else before if v.bust else before-v.score,
          v.bust,v.checkout,v.bullfinish)
        if v.checkout:
            await db.execute(f'''UPDATE {SCHEMA}.match_legs SET winner_id=$2,darts_winner=$3,finished_at=now()
                WHERE id=$1''',leg['id'],player_id,
                sum(old['darts'] for old in current['visits'] if old['leg_index']==leg_number and old['player']==player))
        totals=await db.fetch(f'''SELECT winner_id,count(*) AS n FROM {SCHEMA}.match_legs
            WHERE match_id=$1 AND winner_id IS NOT NULL GROUP BY winner_id''',mid)
        legs_total={row['winner_id']:row['n'] for row in totals}
        total_one=legs_total.get(m['player1_id'],0);total_two=legs_total.get(m['player2_id'],0)
        await db.execute(f'''UPDATE {SCHEMA}.matches SET state=$2::jsonb,state_version=state_version+1,
           status=CASE WHEN $3 THEN 'finished' ELSE 'running' END,
           legs1=CASE WHEN $3 THEN $4 ELSE legs1 END,legs2=CASE WHEN $3 THEN $5 ELSE legs2 END,
           sets1=CASE WHEN $3 THEN $6 ELSE sets1 END,sets2=CASE WHEN $3 THEN $7 ELSE sets2 END,
           finished_at=CASE WHEN $3 THEN now() ELSE finished_at END WHERE id=$1''',
           mid,json.dumps(current),g.done,total_one,total_two,g.sets[0],g.sets[1])
        await db.execute(f"INSERT INTO {SCHEMA}.match_revisions(match_id,actor_id,action,previous_state,new_state) VALUES($1,$2,'throw',$3::jsonb,$4::jsonb)",mid,a['id'],json.dumps(previous),json.dumps(current))
        # There is one revision per valid throw; append-only history supports proper recovery and review.
        await db.execute(f"UPDATE {SCHEMA}.match_claims SET lease_until=now()+interval '45 minutes',released_at=CASE WHEN $2 THEN now() ELSE NULL END WHERE match_id=$1",mid,g.done)
        if g.done and m['kind']=='ladder':await apply_elo(db,m,[total_one,total_two],g.sets)
    return response({'state':current,'version':m['state_version']+1,'summary':g.summary() if g.done else None})

async def undo_visit(req):
    """Undo the last visit of a running match. Completed ELO matches remain final."""
    a=await actor(req);d=await body(req);mid=uid(req.match_info['mid'])
    async with pool(req).acquire() as db:
      async with db.transaction():
        m=await db.fetchrow(f'SELECT * FROM {SCHEMA}.matches WHERE id=$1 FOR UPDATE',mid)
        if not m or m['status']!='running':raise web.HTTPConflict(text='Nur laufende Spiele können korrigiert werden')
        if a['role']=='member' and a['player_id'] not in (m['player1_id'],m['player2_id']):raise web.HTTPForbidden()
        claim=await db.fetchrow(f'SELECT account_id,token_hash,lease_until FROM {SCHEMA}.match_claims WHERE match_id=$1',mid)
        if not claim or claim['account_id']!=a['id'] or claim['token_hash']!=token_digest(req.cookies.get(COOKIE,'')) or claim['lease_until']<=datetime.now(timezone.utc):
            raise web.HTTPConflict(text='Dieses Match gehört nicht zu deiner aktuellen Sitzung')
        if m['state_version']!=int(d.get('version',-1)):raise web.HTTPConflict(text='Spielstand wurde bereits geändert')
        revision=await db.fetchrow(f"SELECT previous_state,new_state FROM {SCHEMA}.match_revisions WHERE match_id=$1 AND action='throw' ORDER BY id DESC LIMIT 1",mid)
        current=as_json(m['state'])
        if not revision or as_json(revision['new_state'])!=current:raise web.HTTPConflict(text='Keine letzte Aufnahme gefunden')
        previous=as_json(revision['previous_state'])
        if len(current.get('visits',[]))!=len(previous.get('visits',[]))+1:raise web.HTTPConflict(text='Ungültiger Spielstand')
        last=current['visits'][-1]
        player=m['player1_id'] if last['player']==0 else m['player2_id']
        leg=int(last['leg_index'])+1
        throw_id=await db.fetchval(f'''SELECT t.id FROM {SCHEMA}.throws t JOIN {SCHEMA}.match_legs l ON l.id=t.leg_id
           WHERE t.match_id=$1 AND l.leg_number=$2 AND t.player_id=$3 ORDER BY t.id DESC LIMIT 1''',mid,leg,player)
        if throw_id is None:raise web.HTTPConflict(text='Archivaufnahme nicht gefunden')
        await db.execute(f'DELETE FROM {SCHEMA}.throws WHERE id=$1',throw_id)
        if last.get('checkout'):
            await db.execute(f'UPDATE {SCHEMA}.match_legs SET winner_id=NULL,darts_winner=NULL,finished_at=NULL WHERE match_id=$1 AND leg_number=$2',mid,leg)
        await db.execute(f'UPDATE {SCHEMA}.matches SET state=$2::jsonb,state_version=state_version+1 WHERE id=$1',mid,json.dumps(previous))
        await db.execute(f'''INSERT INTO {SCHEMA}.match_revisions(match_id,actor_id,action,previous_state,new_state)
          VALUES($1,$2,'undo',$3::jsonb,$4::jsonb)''',mid,a['id'],json.dumps(current),json.dumps(previous))
        await db.execute(f"UPDATE {SCHEMA}.match_claims SET lease_until=now()+interval '45 minutes' WHERE match_id=$1",mid)
    return response({'state':previous,'version':m['state_version']+1})

async def apply_elo(db,m,legs,sets):
    cid=m['competition_id'];a=m['player1_id'];b=m['player2_id']
    for pid in (a,b):
        await db.execute(f'''INSERT INTO {SCHEMA}.ladder_ratings(competition_id,player_id)
             VALUES($1,$2) ON CONFLICT DO NOTHING''',cid,pid)
    ratings=await db.fetch(f'''SELECT player_id,elo FROM {SCHEMA}.ladder_ratings
         WHERE competition_id=$1 AND player_id=ANY($2::uuid[]) ORDER BY player_id FOR UPDATE''',cid,[a,b])
    old={r['player_id']:float(r['elo']) for r in ratings}
    sa,sb=(sets if sum(sets)>0 else legs)
    results=[(a,1 if sa>sb else 0 if sa<sb else .5,legs[0],legs[1]),
             (b,1 if sb>sa else 0 if sb<sa else .5,legs[1],legs[0])]
    for pid,outcome,lf,la in results:
        other=b if pid==a else a;delta,expected=elo_change(old[pid],old[other],outcome)
        await db.execute(f'''UPDATE {SCHEMA}.ladder_ratings SET elo=elo+$3::numeric,played=played+1,
           wins=wins+$4,draws=draws+$5,losses=losses+$6,legs_for=legs_for+$7,legs_against=legs_against+$8
           WHERE competition_id=$1 AND player_id=$2''',cid,pid,delta,int(outcome==1),int(outcome==.5),int(outcome==0),lf,la)
        await db.execute(f'''INSERT INTO {SCHEMA}.ladder_events(competition_id,match_id,player_id,elo_before,expected,outcome,k_factor,elo_change,elo_after)
           VALUES($1,$2,$3,$4,$5,$6,64,$7,$8)''',cid,m['id'],pid,old[pid],expected,outcome,delta,old[pid]+delta)

async def manual_result(req):
    a=await actor(req,'admin');d=await body(req);mid=uid(req.match_info['mid'])
    x,y=int(d.get('legs1',-1)),int(d.get('legs2',-1))
    if x<0 or y<0 or x>101 or y>101:raise web.HTTPBadRequest(text='Ungültige Legzahl')
    async with pool(req).acquire() as db:
      async with db.transaction():
        m=await db.fetchrow(f'SELECT * FROM {SCHEMA}.matches WHERE id=$1 FOR UPDATE',mid)
        if not m or m['status']!='open':raise web.HTTPConflict(text='Nur offene Matches können als Altdaten erfasst werden')
        if await db.fetchval(f"SELECT kind FROM {SCHEMA}.competitions WHERE id=$1",m['competition_id'])=='ladder':
            raise web.HTTPForbidden(text='Ladder wertet nur gescorte Matches')
        await db.execute(f'''UPDATE {SCHEMA}.matches SET status='finished',source='legacy',legs1=$2,legs2=$3,
           finished_at=now() WHERE id=$1''',mid,x,y)
        await db.execute(f"INSERT INTO {SCHEMA}.match_revisions(match_id,actor_id,action,new_state) VALUES($1,$2,'manual_result',$3::jsonb)",mid,a['id'],json.dumps({'legs1':x,'legs2':y}))
    return response({'ok':True})

async def withdraw(req):
    a=await actor(req,'admin');d=await body(req);cid=uid(req.match_info['cid']);pid=uid(d.get('player_id'))
    forfeit=int(d.get('forfeit_legs',4))
    if not 1<=forfeit<=20:raise web.HTTPBadRequest(text='Ungültiges Forfait')
    async with pool(req).acquire() as db:
      async with db.transaction():
        c=await db.fetchrow(f'SELECT kind FROM {SCHEMA}.competitions WHERE id=$1 FOR UPDATE',cid)
        if not c or c['kind']!='league':raise web.HTTPBadRequest(text='Rückwertung nur in der League')
        if await db.fetchval(f'SELECT EXISTS(SELECT 1 FROM {SCHEMA}.withdrawals WHERE competition_id=$1 AND player_id=$2)',cid,pid):
            raise web.HTTPConflict(text='Rückzug schon erfasst')
        ms=await db.fetch(f'''SELECT * FROM {SCHEMA}.matches WHERE competition_id=$1
          AND (player1_id=$2 OR player2_id=$2) FOR UPDATE''',cid,pid)
        originals=[{'id':str(m['id']),'status':m['status'],'source':m['source'],'legs1':m['legs1'],
                   'legs2':m['legs2'],'sets1':m['sets1'],'sets2':m['sets2'],
                   'finished_at':m['finished_at'].isoformat() if m['finished_at'] else None} for m in ms]
        for m in ms:
            await db.execute(f'''UPDATE {SCHEMA}.matches SET status='finished',source='forfeit',legs1=$2,legs2=$3,
             sets1=NULL,sets2=NULL,finished_at=now() WHERE id=$1''',m['id'],0 if m['player1_id']==pid else forfeit,0 if m['player2_id']==pid else forfeit)
        await db.execute(f'''INSERT INTO {SCHEMA}.withdrawals(competition_id,player_id,forfeit_legs,original_results,actor_id)
             VALUES($1,$2,$3,$4::jsonb,$5)''',cid,pid,forfeit,json.dumps(originals),a['id'])
        await db.execute(f"UPDATE {SCHEMA}.entries SET status='withdrawn' WHERE competition_id=$1 AND player_id=$2",cid,pid)
    return response({'revalued':len(ms)})

async def close_phase(req):
    a=await actor(req);pid=uid(req.match_info['pid']);await body(req)
    async with pool(req).acquire() as db:
      async with db.transaction():
        p=await db.fetchrow(f'SELECT * FROM {SCHEMA}.phases WHERE id=$1 FOR UPDATE',pid)
        if not p:raise web.HTTPNotFound()
        await require_manager(db,a,p['competition_id'])
        remaining=await db.fetchval(f"SELECT count(*) FROM {SCHEMA}.matches WHERE phase_id=$1 AND status IN ('open','running')",pid)
        if remaining:raise web.HTTPConflict(text=f'{remaining} offene oder laufende Begegnungen')
        await db.execute(f"UPDATE {SCHEMA}.phases SET status='closed',closed_by=$2,closed_at=now() WHERE id=$1",pid,a['id'])
    return response({'closed':True})

async def bracket(req):
    a=await actor(req);d=await body(req);pid=uid(req.match_info['pid']);ids=d.get('player_ids',[])
    if not isinstance(ids,list) or not 2<=len(ids)<=128:raise web.HTTPBadRequest(text='2–128 gesetzte Spieler erforderlich')
    pairs=bracket_pairs([uid(p) for p in ids]);created=0
    async with pool(req).acquire() as db:
      async with db.transaction():
        p=await db.fetchrow(f'''SELECT p.*,c.kind FROM {SCHEMA}.phases p
             JOIN {SCHEMA}.competitions c ON c.id=p.competition_id WHERE p.id=$1 FOR UPDATE OF p''',pid)
        if not p or p['kind']!='knockout':raise web.HTTPBadRequest(text='Keine K.O.-Phase')
        await require_manager(db,a,p['competition_id'])
        if await db.fetchval(f'SELECT count(*) FROM {SCHEMA}.matches WHERE phase_id=$1',pid):raise web.HTTPConflict(text='K.O.-Phase enthält schon Begegnungen')
        valid={r['player_id'] for r in await db.fetch(f'SELECT player_id FROM {SCHEMA}.entries WHERE competition_id=$1',p['competition_id'])}
        if len(set(ids))!=len(ids) or any(v not in valid for v in [uid(x) for x in ids]):raise web.HTTPBadRequest(text='Ungültige Setzliste')
        rules=mode_rules(p['kind'],'knockout',overrides=d.get('rules') or {})
        for i,(x,y) in enumerate(pairs):
            if x and y:
                await db.execute(f'''INSERT INTO {SCHEMA}.matches(competition_id,phase_id,round_number,bracket_position,player1_id,player2_id,rules)
                   VALUES($1,$2,1,$3,$4,$5,$6::jsonb)''',p['competition_id'],pid,i+1,x,y,json.dumps(rules));created+=1
            # Byes are represented in the bracket preview, not fake games.
    return response({'created':created,'byes':sum(1 for x,y in pairs if x is None or y is None),'pairs':pairs})

async def advance_knockout(req):
    a=await actor(req);d=await body(req);pid=uid(req.match_info['pid'])
    async with pool(req).acquire() as db:
      async with db.transaction():
        p=await db.fetchrow(f'''SELECT p.*,c.kind FROM {SCHEMA}.phases p JOIN {SCHEMA}.competitions c
            ON c.id=p.competition_id WHERE p.id=$1 FOR UPDATE OF p''',pid)
        if not p or p['kind']!='knockout':raise web.HTTPBadRequest(text='Keine K.O.-Phase')
        await require_manager(db,a,p['competition_id'])
        mx=await db.fetchval(f'SELECT max(round_number) FROM {SCHEMA}.matches WHERE phase_id=$1',pid)
        if mx is None:raise web.HTTPConflict(text='Setzliste fehlt')
        rows=await db.fetch(f'SELECT * FROM {SCHEMA}.matches WHERE phase_id=$1 AND round_number=$2 ORDER BY bracket_position',pid,mx)
        if any(m['status']!='finished' for m in rows):raise web.HTTPConflict(text='Runde noch nicht abgeschlossen')
        if len(rows)<2:raise web.HTTPConflict(text='Finale erreicht')
        winners=[]
        for m in rows:
            aa,bb=(m['sets1'],m['sets2']) if (m['sets1'] or m['sets2']) else (m['legs1'],m['legs2'])
            if aa==bb:raise web.HTTPConflict(text='K.O.-Unentschieden nicht zulässig')
            winners.append(m['player1_id'] if aa>bb else m['player2_id'])
        if len(winners)%2:raise web.HTTPConflict(text='Ungerade Siegerzahl: Freiloszuordnung erforderlich')
        for i in range(0,len(winners),2):
            rules=mode_rules(p['kind'],'knockout',final=len(winners)==2,overrides=d.get('rules') or {})
            await db.execute(f'''INSERT INTO {SCHEMA}.matches(competition_id,phase_id,round_number,bracket_position,
                  player1_id,player2_id,rules) VALUES($1,$2,$3,$4,$5,$6,$7::jsonb)''',
                  p['competition_id'],pid,mx+1,i//2+1,winners[i],winners[i+1],json.dumps(rules))
    return response({'created':len(winners)//2,'round':mx+1})

async def end_ladder(req):
    await actor(req,'admin');cid=uid(req.match_info['cid']);await body(req)
    async with pool(req).acquire() as db:
      async with db.transaction():
        c=await db.fetchrow(f'SELECT kind,ends_at FROM {SCHEMA}.competitions WHERE id=$1 FOR UPDATE',cid)
        if not c or c['kind']!='ladder':raise web.HTTPBadRequest(text='Keine Ladder')
        if not c['ends_at'] or datetime.now(timezone.utc)<c['ends_at']:
            raise web.HTTPConflict(text='Das Saisonende ist noch nicht erreicht')
        count=await db.fetchval(f"SELECT count(*) FROM {SCHEMA}.matches WHERE competition_id=$1 AND status IN ('open','running')",cid)
        await db.execute(f"UPDATE {SCHEMA}.matches SET status='cancelled' WHERE competition_id=$1 AND status IN ('open','running')",cid)
        await db.execute(f"UPDATE {SCHEMA}.competitions SET status='finished' WHERE id=$1",cid)
    return response({'cancelled_unscored':count,'elo_frozen':True})

async def competition_status(req):
    await actor(req,'admin');d=await body(req);cid=uid(req.match_info['cid'])
    status=d.get('status')
    if status not in ('draft','active','finished','archived'):raise web.HTTPBadRequest(text='Ungültiger Status')
    async with pool(req).acquire() as db:
        await db.execute(f'UPDATE {SCHEMA}.competitions SET status=$2 WHERE id=$1 AND deleted_at IS NULL',cid,status)
    return response({'status':status})

async def export_open(req):
    await actor(req);cid=uid(req.match_info['cid']);fmt=req.query.get('format','csv')
    async with pool(req).acquire() as db:
        c=await db.fetchrow(f'SELECT kind FROM {SCHEMA}.competitions WHERE id=$1',cid)
        if not c or c['kind']=='training_tournament':raise web.HTTPForbidden(text='Export für dieses Turnier nicht verfügbar')
        rows=await db.fetch(f'''SELECT m.id,g.name AS gruppe,m.round_number AS runde,p1.display_name AS spieler1,
             p2.display_name AS spieler2,m.status FROM {SCHEMA}.matches m
             JOIN {SCHEMA}.players p1 ON p1.id=m.player1_id JOIN {SCHEMA}.players p2 ON p2.id=m.player2_id
             LEFT JOIN {SCHEMA}.groups g ON g.id=m.group_id WHERE m.competition_id=$1 AND m.status='open'
             ORDER BY g.sort_order NULLS LAST,m.round_number,p1.display_name''',cid)
    data=[dict(r) for r in rows]
    if fmt=='xlsx':
        from openpyxl import Workbook
        b=Workbook();w=b.active;w.title='Offene Spiele';headers=['Match-ID','Gruppe','Runde','Spieler 1','Spieler 2','Status'];w.append(headers)
        for r in data:w.append([str(r.get(k) or '') for k in ('id','gruppe','runde','spieler1','spieler2','status')])
        stream=io.BytesIO();b.save(stream)
        return web.Response(body=stream.getvalue(),headers={'Content-Disposition':'attachment; filename="offene-spiele.xlsx"'},content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    if fmt!='csv':raise web.HTTPBadRequest(text='Format csv oder xlsx')
    stream=io.StringIO();w=csv.writer(stream,delimiter=';');w.writerow(['Match-ID','Gruppe','Runde','Spieler 1','Spieler 2','Status'])
    for r in data:w.writerow([r.get(k) for k in ('id','gruppe','runde','spieler1','spieler2','status')])
    return web.Response(body=('\ufeff'+stream.getvalue()).encode('utf-8'),headers={'Content-Disposition':'attachment; filename="offene-spiele.csv"'},content_type='text/csv; charset=utf-8')

async def stats(req):
    await actor(req);pid=uid(req.match_info['pid']);kind=req.query.get('kind','overall')
    selected_competition=uid(req.query['competition_id']) if req.query.get('competition_id') else None
    if kind not in ('overall',*KINDS):raise web.HTTPBadRequest(text='Ungültiger Statistikfilter')
    async with pool(req).acquire() as db:
        sql=f'''SELECT m.id,m.status,m.source,m.legs1,m.legs2,m.sets1,m.sets2,m.player1_id,m.player2_id,m.state,
          c.kind,c.title FROM {SCHEMA}.matches m JOIN {SCHEMA}.competitions c ON c.id=m.competition_id
          WHERE c.deleted_at IS NULL AND m.status='finished' AND (m.player1_id=$1 OR m.player2_id=$1)'''
        params=[pid]
        if kind!='overall':sql+=' AND c.kind=$2';params.append(kind)
        if selected_competition:
            params.append(selected_competition)
            sql+=f' AND m.competition_id=${len(params)}'
        games=await db.fetch(sql,*params)
        scored=await db.fetch(f'''SELECT t.points,t.darts,t.is_bust,t.is_checkout,t.is_bullfinish,m.competition_id,c.kind
          FROM {SCHEMA}.throws t JOIN {SCHEMA}.matches m ON m.id=t.match_id
          JOIN {SCHEMA}.competitions c ON c.id=m.competition_id
          WHERE t.player_id=$1 AND c.deleted_at IS NULL AND m.status='finished' AND m.source='scorer' ''',pid)
    if kind!='overall':scored=[s for s in scored if s['kind']==kind]
    if selected_competition:scored=[s for s in scored if s['competition_id']==selected_competition]
    games=list(games);scored=list(scored)
    if kind in ('overall','training_tournament') and not selected_competition:
        # Standalone X01 practice lives in its own table and never affects league/cup/ladder.
        async with pool(req).acquire() as db:
            free_games=await db.fetch(f'''SELECT player1_id,player2_id,state,status
                FROM {SCHEMA}.free_x01_matches WHERE status='finished'
                  AND (player1_id=$1 OR player2_id=$1)''',pid)
        for m in free_games:
            raw=as_json(m['state']);legs=raw.get('legs') or [0,0];sets=raw.get('sets') or [0,0]
            games.append({'player1_id':m['player1_id'],'player2_id':m['player2_id'],
                'legs1':legs[0],'legs2':legs[1],'sets1':sets[0],'sets2':sets[1],
                'source':'scorer','state':raw})
            me=0 if m['player1_id']==pid else 1
            for visit in raw.get('visits',[]):
                if visit.get('player')!=me:continue
                scored.append({'points':int(visit['score']),'darts':int(visit.get('darts',3)),
                     'is_bust':bool(visit.get('bust')),'is_checkout':bool(visit.get('checkout')),
                     'is_bullfinish':bool(visit.get('bullfinish'))})
    solo=[]
    if kind in ('overall','training_tournament') and not selected_competition:
        async with pool(req).acquire() as db:
            solo=await db.fetch(f'''SELECT kind,result FROM {SCHEMA}.training_sessions WHERE player_id=$1''',pid)
    wins=draws=losses=legs_for=legs_against=0
    for m in games:
        left=m['player1_id']==pid
        x,y=(m['sets1'],m['sets2']) if (m['sets1'] or m['sets2']) else (m['legs1'],m['legs2'])
        if not left:x,y=y,x
        legs_for+=m['legs1' if left else 'legs2'] or 0;legs_against+=m['legs2' if left else 'legs1'] or 0
        if x>y:wins+=1
        elif x==y:draws+=1
        else:losses+=1
    # Precise First 9, lowdarts and highest finishes derive only from saved scorer
    # visits, never from manual or legacy scores.
    first9_score=first9_darts=0;lowdarts=[];highfinishes=[];bull_finishes=[];highscores=[]
    for m in games:
        if m['source']!='scorer':continue
        raw=as_json(m['state'])
        visits=raw.get('visits') or []
        player_index=0 if m['player1_id']==pid else 1
        own=[v for v in visits if v.get('player')==player_index]
        legs={}
        for v in own:legs.setdefault(v.get('leg_index',0),[]).append(v)
        for items in legs.values():
            n=0
            for v in items:
                nd=int(v.get('darts',3))
                if n+nd>9:break
                n+=nd;first9_darts+=nd
                if not v.get('bust'):first9_score+=int(v.get('score',0))
            finished=[v for v in items if v.get('checkout')]
            if finished:
                total=sum(int(v.get('darts',3)) for v in items)
                if 9<=total<=18:lowdarts.append(total)
                value=int(finished[-1].get('score',0))
                if value>=100:highfinishes.append(value)
                if finished[-1].get('bullfinish'):bull_finishes.append(value)
        highscores.extend(int(v.get('score',0)) for v in own if int(v.get('score',0))>=171 and not v.get('bust'))
    sau_results=[as_json(v['result']) for v in solo if v['kind']=='sau']
    bobs_results=[as_json(v['result']) for v in solo if v['kind']=='bobs27']
    tug_count=0
    if kind in ('overall','training_tournament') and not selected_competition:
        async with pool(req).acquire() as db:
            tug_count=await db.fetchval(f'''SELECT count(*) FROM {SCHEMA}.training_tug_sessions
                 WHERE player_id=$1 OR opponent_id=$1''',pid)
    points=sum(s['points'] for s in scored if not s['is_bust']);darts=sum(s['darts'] for s in scored)
    return response({'matches':len(games),'wins':wins,'draws':draws,'losses':losses,'legs_for':legs_for,
        'legs_against':legs_against,'scored_visits':len(scored),'average':round(points/darts*3,2) if darts else None,
        'first9':round(3*first9_score/first9_darts,2) if first9_darts else None,
        'lowdarts':len(lowdarts),'lowdart_details':sorted(lowdarts),
        'highfinishes':len(highfinishes),'highfinish_details':sorted(highfinishes,reverse=True),
        'bullfinish_details':bull_finishes,'highscores':highscores[:30],
        '180':sum(s['points']==180 and not s['is_bust'] for s in scored),
        '140plus':sum(s['points']>=140 and not s['is_bust'] for s in scored),
        '171plus':sum(s['points']>=171 and not s['is_bust'] for s in scored),
        '100plus':sum(s['points']>=100 and not s['is_bust'] for s in scored),
        'bullfinishes':sum(bool(s['is_bullfinish']) for s in scored),
        'training_sau_sessions':len(sau_results),'training_bobs_sessions':len(bobs_results),
        'training_tug_sessions':tug_count,
        'training_sau_success':sum(int(x.get('checkouts',0)) for x in sau_results),
        'training_sau_marks':sum(int(x.get('sau',0)) for x in sau_results),
        'training_bobs_best':max([int(x.get('points',0)) for x in bobs_results],default=None),
        'missing_throw_stats_matches':sum(m['source']!='scorer' for m in games)})

async def save_solo_session(req):
    a=await actor(req);d=await body(req)
    kind=d.get('kind');result=d.get('result')
    if kind not in ('sau','bobs27') or not isinstance(result,dict):raise web.HTTPBadRequest(text='Unbekanntes Trainingsformat')
    if not a['player_id']:raise web.HTTPForbidden(text='Ein verknüpftes Spielerprofil ist für Trainingsstatistiken erforderlich')
    # Bound JSON size; the final summary is persisted, not each individual keystroke.
    if len(json.dumps(result))>20_000:raise web.HTTPBadRequest(text='Trainingsdaten zu groß')
    async with pool(req).acquire() as db:
        row=await db.fetchrow(f'''INSERT INTO {SCHEMA}.training_sessions(player_id,kind,result)
           VALUES($1,$2,$3::jsonb) RETURNING id,created_at''',a['player_id'],kind,json.dumps(result))
    return response(dict(row),201)

async def save_tug_session(req):
    a=await actor(req);d=await body(req)
    if not a['player_id']:raise web.HTTPForbidden(text='Spielerprofil fehlt')
    other=uid(d.get('opponent_id'))
    result=d.get('result')
    if other==a['player_id'] or not isinstance(result,dict) or len(json.dumps(result))>50000:
        raise web.HTTPBadRequest(text='Ungültiges Tauziehen-Ergebnis')
    async with pool(req).acquire() as db:
        item=await db.fetchrow(f'''INSERT INTO {SCHEMA}.training_tug_sessions(player_id,opponent_id,result)
             VALUES($1,$2,$3::jsonb) RETURNING id''',a['player_id'],other,json.dumps(result))
    return response({'id':item['id']},201)

async def head_to_head(req):
    await actor(req);pid=uid(req.match_info['pid']);kind=req.query.get('kind','overall')
    selected_competition=uid(req.query['competition_id']) if req.query.get('competition_id') else None
    if kind not in ('overall',*KINDS):raise web.HTTPBadRequest(text='Ungültiger Filter')
    async with pool(req).acquire() as db:
        rows=await db.fetch(f'''SELECT m.player1_id,m.player2_id,m.legs1,m.legs2,m.sets1,m.sets2,
         p1.display_name AS name1,p2.display_name AS name2,c.kind
         FROM {SCHEMA}.matches m JOIN {SCHEMA}.competitions c ON c.id=m.competition_id
         JOIN {SCHEMA}.players p1 ON p1.id=m.player1_id JOIN {SCHEMA}.players p2 ON p2.id=m.player2_id
         WHERE c.deleted_at IS NULL AND m.status='finished' AND
         (m.player1_id=$1 OR m.player2_id=$1) AND ($2::uuid IS NULL OR m.competition_id=$2)
         ORDER BY m.finished_at DESC''',pid,selected_competition)
    rows=list(rows)
    if kind in ('overall','training_tournament') and not selected_competition:
        async with pool(req).acquire() as db:
            free=await db.fetch(f'''SELECT m.player1_id,m.player2_id,m.state,
              p1.display_name AS name1,p2.display_name AS name2
              FROM {SCHEMA}.free_x01_matches m
              JOIN {SCHEMA}.players p1 ON p1.id=m.player1_id
              JOIN {SCHEMA}.players p2 ON p2.id=m.player2_id
              WHERE m.status='finished' AND (m.player1_id=$1 OR m.player2_id=$1)''',pid)
            for m in free:
                state=as_json(m['state']);legs=state.get('legs') or [0,0];sets=state.get('sets') or [0,0]
                rows.append({'player1_id':m['player1_id'],'player2_id':m['player2_id'],
                    'legs1':legs[0],'legs2':legs[1],'sets1':sets[0],'sets2':sets[1],
                    'name1':m['name1'],'name2':m['name2'],'kind':'training_tournament'})
    out={}
    for m in rows:
        if kind!='overall' and m['kind']!=kind:continue
        left=m['player1_id']==pid;other=m['player2_id'] if left else m['player1_id']
        name=m['name2'] if left else m['name1']
        record=out.setdefault(str(other),{'opponent':name,'played':0,'wins':0,'draws':0,'losses':0,'legs_for':0,'legs_against':0})
        a=int((m['legs1'] if left else m['legs2']) or 0);b=int((m['legs2'] if left else m['legs1']) or 0)
        sa=int((m['sets1'] if left else m['sets2']) or 0);sb=int((m['sets2'] if left else m['sets1']) or 0)
        x,y=(sa,sb) if sa or sb else (a,b)
        record['played']+=1;record['legs_for']+=a;record['legs_against']+=b
        if x>y:record['wins']+=1
        elif x<y:record['losses']+=1
        else:record['draws']+=1
    return response(sorted(out.values(),key=lambda x:(-x['played'],x['opponent'].casefold())))

async def elo_history(req):
    await actor(req);cid=uid(req.match_info['cid'])
    async with pool(req).acquire() as db:
        rows=await db.fetch(f'''SELECT e.*,p.display_name FROM {SCHEMA}.ladder_events e
            JOIN {SCHEMA}.players p ON p.id=e.player_id WHERE e.competition_id=$1 ORDER BY e.created_at DESC LIMIT 1000''',cid)
    return response(list(map(dict,rows)))

async def overview(req):
    a=await actor(req)
    preview=req.query.get('player_id')
    if preview and a['role']!='admin':raise web.HTTPForbidden(text='Nur Admin darf Spieleransicht nutzen')
    viewed=uid(preview) if preview else a['player_id']
    async with pool(req).acquire() as db:
        entries=await db.fetch(f'''SELECT c.id,c.title,c.kind,c.status,count(m.id) FILTER(WHERE m.status='open') AS open_games
          FROM {SCHEMA}.competitions c LEFT JOIN {SCHEMA}.matches m ON m.competition_id=c.id
          WHERE c.deleted_at IS NULL GROUP BY c.id ORDER BY c.created_at DESC LIMIT 30''')
        own=[]
        if viewed:
            own=await db.fetch(f'''SELECT m.id,c.title,c.kind,p1.display_name AS player1,p2.display_name AS player2
                FROM {SCHEMA}.matches m JOIN {SCHEMA}.competitions c ON c.id=m.competition_id
                JOIN {SCHEMA}.players p1 ON p1.id=m.player1_id JOIN {SCHEMA}.players p2 ON p2.id=m.player2_id
                WHERE c.deleted_at IS NULL AND m.status='open' AND (m.player1_id=$1 OR m.player2_id=$1)
                LIMIT 30''',viewed)
    return response({'competitions':list(map(dict,entries)),'own_open':list(map(dict,own)),'viewed_player_id':viewed,'preview':bool(preview)})

async def register_startup(app):
    url=os.environ.get('STINGRAYS_DATABASE_URL')
    if not url:
        print('[STINGRAYS V2] disabled: STINGRAYS_DATABASE_URL not set')
        app['stingrays_pool']=None
        return
    import asyncpg
    # Neon pooled endpoint; a maximum of 3 connections avoids persistent compute load.
    app['stingrays_pool']=await asyncpg.create_pool(dsn=url,min_size=0,max_size=3,command_timeout=20,
                                             max_inactive_connection_lifetime=30)
    print('[STINGRAYS V2] Neon connection ready')

async def register_cleanup(app):
    p=app.get('stingrays_pool')
    if p:await p.close()

def register_stingrays_v2(app):
    app.on_startup.append(register_startup);app.on_cleanup.append(register_cleanup)
    from .free_training import register as register_free_training
    register_free_training(app)
    routes=[
      ('GET','/dart/v2',spa),('GET','/dart/v2/',spa),('GET','/dart/v2/spiel/',legacy_scorer_page),('GET','/dart/v2/assets/{filename}',assets),
      ('GET','/dart/v2/api/health',health),
      ('GET','/dart/v2/api/legacy/preview',preview_legacy),
      ('POST','/dart/v2/api/legacy/sync-profiles',sync_legacy_profiles),
      ('POST','/dart/v2/api/legacy/import',import_legacy),('POST','/dart/v2/api/bootstrap',bootstrap),
      ('POST','/dart/v2/api/login',login),('POST','/dart/v2/api/logout',logout),
      ('GET','/dart/v2/api/me',me),('POST','/dart/v2/api/password',password),
      ('GET','/dart/v2/api/dashboard',overview),('GET','/dart/v2/api/players',members),
      ('POST','/dart/v2/api/players',create_member),('POST','/dart/v2/api/accounts',create_account),
      ('POST','/dart/v2/api/accounts/{aid}',reset_account),
      ('GET','/dart/v2/api/boards',board_list),('POST','/dart/v2/api/boards/{bid}',edit_board),
      ('GET','/dart/v2/api/competitions',competition_list),('POST','/dart/v2/api/competitions',create_competition),
      ('GET','/dart/v2/api/competitions/{cid}',competition_detail),
      ('POST','/dart/v2/api/competitions/{cid}/entries',add_entries),
      ('POST','/dart/v2/api/competitions/{cid}/phases',create_phase),
      ('POST','/dart/v2/api/phases/{pid}/groups',create_group),
      ('POST','/dart/v2/api/groups/{gid}/entries',assign_group),
      ('POST','/dart/v2/api/groups/{gid}/fixtures',generate_rounds),
      ('POST','/dart/v2/api/competitions/{cid}/matches',create_match),
      ('GET','/dart/v2/api/competitions/{cid}/standings',standings),
      ('GET','/dart/v2/api/matches/{mid}',match_state),
      ('POST','/dart/v2/api/matches/{mid}/start',start_match),
      ('POST','/dart/v2/api/matches/{mid}/throw',throw),('POST','/dart/v2/api/matches/{mid}/undo',undo_visit),
      ('POST','/dart/v2/api/matches/{mid}/manual',manual_result),
      ('POST','/dart/v2/api/competitions/{cid}/withdraw',withdraw),
      ('POST','/dart/v2/api/phases/{pid}/close',close_phase),
      ('POST','/dart/v2/api/phases/{pid}/bracket',bracket),
      ('POST','/dart/v2/api/phases/{pid}/advance',advance_knockout),
      ('POST','/dart/v2/api/competitions/{cid}/end-ladder',end_ladder),
      ('POST','/dart/v2/api/competitions/{cid}/status',competition_status),
      ('POST','/dart/v2/api/competitions/{cid}/delete',delete_competition),
      ('GET','/dart/v2/api/competitions/{cid}/export',export_open),
      ('GET','/dart/v2/api/competitions/{cid}/elo-history',elo_history),
      ('GET','/dart/v2/api/players/{pid}/stats',stats),
      ('GET','/dart/v2/api/players/{pid}/h2h',head_to_head),
      ('POST','/dart/v2/api/training/sessions',save_solo_session),
      ('POST','/dart/v2/api/training/tug',save_tug_session),
    ]
    for method,path,handler in routes:app.router.add_route(method,path,handler)
    print('[STINGRAYS V2] release r20261022-ui-scoring-roles installed under /dart/v2/')

# The existing Google-Sheets League remains authoritative until an administrator
# explicitly imports a checked copy. No old record is mutated by these routes.
async def preview_legacy(req):
    await actor(req,'admin')
    from dart_league import LEAGUES
    return response({'leagues':[{'legacy_id':key,'name':v.get('name'),
        'groups':len(v.get('groups',[])),'fixtures':len(v.get('fixtures',[])),
        'completed':sum(f.get('legs') is not None for f in v.get('fixtures',[])),
        'in_progress':sum(bool(f.get('game') and f['game'].get('visits')) and f.get('legs') is None for f in v.get('fixtures',[]))}
        for key,v in LEAGUES.items() if not v.get('deleted')]})

async def sync_legacy_profiles(req):
    await actor(req,'admin');await body(req)
    from dart_profiles_store import profiles as load_profiles
    items=await load_profiles()
    async with pool(req).acquire() as db:
        async with db.transaction():
            for p in items:
                await db.execute(f'''INSERT INTO {SCHEMA}.players(legacy_profile_id,display_name,is_member,is_active)
                    VALUES($1,$2,true,true) ON CONFLICT(legacy_profile_id) DO UPDATE
                    SET display_name=EXCLUDED.display_name''',p['id'],p['display_name'])
    return response({'synced_active_profiles':len(items),'note':'Alte Profildaten nicht verändert'})

async def import_legacy(req):
    await actor(req,'admin');d=await body(req)
    from dart_league import LEAGUES
    source_id=str(d.get('legacy_id',''))
    legacy=LEAGUES.get(source_id)
    if not legacy or legacy.get('deleted'):raise web.HTTPNotFound(text='Alte Liga nicht gefunden')
    if not d.get('confirm'):raise web.HTTPBadRequest(text='Ausdrückliche Importbestätigung erforderlich')
    if any(f.get('game') and f['game'].get('visits') and f.get('legs') is None for f in legacy['fixtures']):
        raise web.HTTPConflict(text='Laufendes Match in der alten League – Import verschieben')
    groups=legacy['groups'];fixtures=legacy['fixtures']
    if any(f['group_id'] not in {g['id'] for g in groups} for f in fixtures):
        raise web.HTTPConflict(text='Ungültiger Gruppenbezug im Snapshot')
    async with pool(req).acquire() as db:
      async with db.transaction():
        await db.execute('SELECT pg_advisory_xact_lock(778191923)')
        exists=await db.fetchval(f"SELECT id FROM {SCHEMA}.competitions WHERE rules->>'legacy_league_id'=$1",source_id)
        if exists:raise web.HTTPConflict(text='Liga wurde bereits importiert')
        metadata={'legacy_league_id':source_id,'points_win':legacy.get('points_win',2),
                  'points_draw':legacy.get('points_draw',1),'start_score':legacy.get('start_score',501)}
        comp=await db.fetchval(f'''INSERT INTO {SCHEMA}.competitions(title,kind,status,rules)
             VALUES($1,'league','draft',$2::jsonb) RETURNING id''',legacy.get('name','Historische League'),json.dumps(metadata))
        phase=await db.fetchval(f'''INSERT INTO {SCHEMA}.phases(competition_id,name,kind,phase_order,status)
             VALUES($1,'Ligaphase','league',1,'open') RETURNING id''',comp)
        pmap={};gmap={}
        for group in groups:
            gid=await db.fetchval(f'''INSERT INTO {SCHEMA}.groups(phase_id,name,sort_order)
               VALUES($1,$2,$3) RETURNING id''',phase,group['name'],len(gmap)+1)
            gmap[group['id']]=gid
            for player in group['players']:
                key=str(player['id'])
                if key not in pmap:
                    pid=await db.fetchval(f'SELECT id FROM {SCHEMA}.players WHERE legacy_profile_id=$1',key)
                    if not pid:
                        pid=await db.fetchval(f'''INSERT INTO {SCHEMA}.players(legacy_profile_id,display_name,is_member,is_active)
                            VALUES($1,$2,$3,true) RETURNING id''',key,player['name'],not key.startswith('GUEST-'))
                    pmap[key]=pid
                    await db.execute(f'''INSERT INTO {SCHEMA}.entries(competition_id,player_id)
                       VALUES($1,$2) ON CONFLICT DO NOTHING''',comp,pid)
                eid=await db.fetchval(f'SELECT id FROM {SCHEMA}.entries WHERE competition_id=$1 AND player_id=$2',comp,pmap[key])
                await db.execute(f'''INSERT INTO {SCHEMA}.group_members(group_id,entry_id)
                    VALUES($1,$2) ON CONFLICT DO NOTHING''',gid,eid)
        for f in fixtures:
            x,y=pmap[str(f['a'])],pmap[str(f['b'])]
            complete=f.get('legs') is not None
            legs=f.get('legs')
            maximum=int(f.get('best_of',legacy.get('best_of',6)))
            configured=mode_rules('league','league',overrides={'start_score':legacy.get('start_score',501),
                                                               'max_legs':maximum,'allow_draw':maximum%2==0})
            await db.execute(f'''INSERT INTO {SCHEMA}.matches(competition_id,phase_id,group_id,round_number,
                player1_id,player2_id,status,source,legs1,legs2,rules,finished_at)
                VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11::jsonb,$12)''',
                comp,phase,gmap[f['group_id']],int(f.get('round',1)),x,y,
                'finished' if complete else 'open','legacy' if complete else None,
                int(legs[0]) if complete else None,int(legs[1]) if complete else None,
                json.dumps(configured),datetime.now(timezone.utc) if complete else None)
    return response({'competition_id':comp,'players':len(pmap),'fixtures':len(fixtures),
       'completed':sum(f.get('legs') is not None for f in fixtures),
       'note':'Historische League als separate Kopie nach Neon übernommen, alte Google Sheets unangetastet.'})

async def delete_competition(req):
    """Soft delete: exclude a competition's matches from active statistics; preserve audit."""
    a=await actor(req,'admin');cid=uid(req.match_info['cid']);d=await body(req)
    if d.get('confirm')!='DAUERHAFT AUSBLENDEN':
        raise web.HTTPBadRequest(text='Explizite Bestätigung erforderlich')
    async with pool(req).acquire() as db:
        async with db.transaction():
            c=await db.fetchrow(f'SELECT status,title FROM {SCHEMA}.competitions WHERE id=$1 FOR UPDATE',cid)
            if not c:raise web.HTTPNotFound()
            if await db.fetchval(f"SELECT count(*) FROM {SCHEMA}.matches WHERE competition_id=$1 AND status='running'",cid):
                raise web.HTTPConflict(text='Laufende Matches müssen zuerst beendet werden')
            await db.execute(f'UPDATE {SCHEMA}.competitions SET deleted_at=now() WHERE id=$1',cid)
            await db.execute(f'''INSERT INTO {SCHEMA}.audit_log(actor_id,action,target_type,target_id,details)
                 VALUES($1,'soft_delete','competition',$2,$3::jsonb)''',a['id'],str(cid),json.dumps({'title':c['title']}))
    return response({'deleted':True,'note':'Aus aktiven Statistiken entfernt; Änderungen protokolliert'})
