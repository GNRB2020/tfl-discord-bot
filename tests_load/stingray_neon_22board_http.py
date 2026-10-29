"""Real HTTP + real asyncpg/Neon 22-board integration stress test.

Runs ONLY against a prepared Neon copy containing the two marker fixtures from
28 Oct. Does not start a public server, connect to Render, or read/write the
production branch. Requires a dedicated GitHub Actions secret:
STINGRAYS_TEST_DATABASE_URL. It deliberately leaves test data on the branch.

Run: python tests_load/stingray_neon_22board_http.py
"""
from __future__ import annotations

import asyncio
from collections import Counter
from contextlib import suppress
import json
import os
import secrets
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

import aiohttp
import asyncpg
from aiohttp import web
from aiohttp.test_utils import TestServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from stingrays_v2 import api
from stingrays_v2.security import hash_password

BOARD_COUNT = 22
# GitHub Actions inputs can select quick (15) vs full (35) and DB pool 3 vs 10.
# Never silently accept arbitrary CI values or unintentionally increase load.
THROWS_PER_BOARD = int(os.environ.get('STINGRAYS_HTTP_THROWS_PER_BOARD', '15'))
POOL_SIZE = int(os.environ.get('STINGRAYS_HTTP_POOL_MAX', '3'))
TIMEOUT_SECONDS = 720
EXPECTED_SENTINEL = '__INT_TEST_22BOARDS_20261028'
PREFIX = '__CI_22BOARD_' + secrets.token_hex(6)
RULES = {'mode':'legs','start_score':501,'max_legs':5,'allow_draw':False,'double_out':True}


def percentile(values, frac):
    values = sorted(values)
    if not values:
        return None
    pos = (len(values)-1)*frac
    ix = int(pos)
    return round(values[ix]+(values[min(ix+1,len(values)-1)]-values[ix])*(pos-ix),2)


async def main():
    if THROWS_PER_BOARD not in (15, 35):
        raise SystemExit('Nur 15 oder 35 Aufnahmen pro Board erlaubt.')
    if POOL_SIZE not in (3, 10):
        raise SystemExit('Nur Poolgrößen 3 oder 10 erlaubt.')
    url = os.environ.get('STINGRAYS_TEST_DATABASE_URL','').strip()
    if not url:
        raise SystemExit('STINGRAYS_TEST_DATABASE_URL fehlt. Kein Test gestartet.')
    host = (urlsplit(url).hostname or '').lower()
    if not host.endswith('.neon.tech'):
        raise SystemExit('Nur eine Neon-Datenbank ist für diesen Test erlaubt.')
    pool = await asyncpg.create_pool(dsn=url, min_size=0, max_size=POOL_SIZE, command_timeout=30)
    app = None
    server = None
    matches = []
    accounts = []
    password = secrets.token_urlsafe(24)
    hashed_password = hash_password(password)
    run_start = time.perf_counter()
    timings = []
    status_counts = Counter()
    errors = []
    per_board_counts = [0] * BOARD_COUNT
    try:
        # Guard is evaluated BEFORE writing anything. The marker exists solely
        # on the already-created, isolated test branch, not on production.
        async with pool.acquire() as conn:
            marker = await conn.fetchval('''SELECT count(*) FROM stingrays_app.competitions
                                            WHERE title=$1''', EXPECTED_SENTINEL)
            named_test_players = await conn.fetchval('''SELECT count(*) FROM stingrays_app.players
                                     WHERE display_name LIKE '__INT_TEST_22BOARDS_20261028_%' ''')
            enabled = await conn.fetchval('''SELECT count(*) FROM stingrays_app.boards WHERE enabled=true''')
        if marker != 1 or named_test_players < 44 or enabled < 22:
            raise RuntimeError('Abbruch vor Datenänderung: Neon-Testbranch-Marker oder 22 Boards fehlen.')

        async with pool.acquire() as conn:
            async with conn.transaction():
                # Release board assignments ONLY from synthetic load-test matches
                # in the cloned branch. Never touch other contests or results.
                await conn.execute('''UPDATE stingrays_app.matches m SET board_id=NULL
                  FROM stingrays_app.competitions c
                  WHERE m.competition_id=c.id AND m.status='running'
                    AND m.board_id IS NOT NULL
                    AND (c.title=$1 OR c.title LIKE '__CI_22BOARD_%')''',EXPECTED_SENTINEL)
                unexpected_busy = await conn.fetchval('''SELECT count(*) FROM stingrays_app.matches m
                   JOIN stingrays_app.competitions c ON c.id=m.competition_id
                   WHERE m.status='running' AND m.board_id IS NOT NULL
                     AND c.title<>$1 AND c.title NOT LIKE '__CI_22BOARD_%' ''',EXPECTED_SENTINEL)
                if unexpected_busy:
                    raise RuntimeError('Fremde aktive Boardbelegung auf dem Testbranch; Abbruch.')
                cid = await conn.fetchval('''INSERT INTO stingrays_app.competitions(title,kind,status,rules)
                  VALUES($1,'league','active','{}'::jsonb) RETURNING id''',PREFIX)
                phase_id = await conn.fetchval('''INSERT INTO stingrays_app.phases(competition_id,name,kind,phase_order,status)
                  VALUES($1,'22-Board-HTTP-Lasttest','league',1,'open') RETURNING id''',cid)
                for i in range(BOARD_COUNT):
                    player1 = await conn.fetchval('''INSERT INTO stingrays_app.players(display_name,is_active,is_member)
                      VALUES($1,true,false) RETURNING id''',f'{PREFIX}-P{i+1:02d}-A')
                    player2 = await conn.fetchval('''INSERT INTO stingrays_app.players(display_name,is_active,is_member)
                      VALUES($1,true,false) RETURNING id''',f'{PREFIX}-P{i+1:02d}-B')
                    account = await conn.fetchval('''INSERT INTO stingrays_app.accounts(player_id,username,password_hash,role,must_change_password,is_enabled)
                      VALUES($1,$2,$3,'tournament',false,true) RETURNING id''',player1,f'{PREFIX.lower()}-{i+1:02d}',hashed_password)
                    mid = await conn.fetchval('''INSERT INTO stingrays_app.matches(competition_id,phase_id,round_number,
                      bracket_position,player1_id,player2_id,status,rules)
                      VALUES($1,$2,1,$3,$4,$5,'open',$6::jsonb) RETURNING id''',cid,phase_id,i+1,player1,player2,json.dumps(RULES))
                    matches.append(mid)
                    accounts.append(f'{PREFIX.lower()}-{i+1:02d}')
                # An additional open game attempts to use an already occupied board.
                extra = await conn.fetchval('''INSERT INTO stingrays_app.matches(competition_id,phase_id,round_number,
                  bracket_position,player1_id,player2_id,status,rules)
                  SELECT competition_id,phase_id,2,23,player1_id,player2_id,'open',rules
                  FROM stingrays_app.matches WHERE id=$1 RETURNING id''',matches[0])

        app = web.Application(middlewares=[api.stingrays_v2_change_audit])
        app['stingrays_pool'] = pool
        app.add_routes([
          web.post('/dart/v2/api/login',api.login),
          web.post('/dart/v2/api/matches/{mid}/start',api.start_match),
          web.post('/dart/v2/api/matches/{mid}/throw',api.throw),
        ])
        server = TestServer(app, host='127.0.0.1', port=0)
        await server.start_server()

        async def post(session, path, data, expected=200, headers=None, capture_statuses=None):
            start = time.perf_counter()
            async with session.post(server.make_url(path),json=data,headers=headers) as r:
                status = r.status
                payload = await r.text()
                raw_cookie = r.cookies.get(api.COOKIE)
            status_counts[status] += 1
            if capture_statuses is not None:capture_statuses.append(status)
            if status == 200:
                timings.append((time.perf_counter()-start)*1000)
            if expected is not None and status != expected:
                errors.append({'path':path,'status':status,'expected':expected,'message':payload[:180]})
            try: out = json.loads(payload)
            except (ValueError,TypeError): out = {}
            return out, (raw_cookie.value if raw_cookie else None)

        async def board_job_no_race(i):
            async with aiohttp.ClientSession(trust_env=False) as session:
                _, token = await post(session,'/dart/v2/api/login',{'username':accounts[i],'password':password})
                if not token:
                    errors.append({'board':i+1,'problem':'login did not create session cookie'})
                    return
                h={'Cookie': f'{api.COOKIE}={token}'}
                if i == 0:board_job_no_race.token = token
                resp,_=await post(session,f'/dart/v2/api/matches/{matches[i]}/start',
                                   {'board_id':i+1,'starter':0},headers=h)
                version=resp.get('version')
                for n in range(THROWS_PER_BOARD):
                    if version is None:
                        errors.append({'board':i+1,'problem':f'no version at visit {n}'})
                        break
                    resp,_=await post(session,f'/dart/v2/api/matches/{matches[i]}/throw',
                           {'points':10,'darts':3,'version':version},headers=h)
                    version=resp.get('version')
                    if version is not None:
                        per_board_counts[i] += 1

        print(json.dumps({'phase':'http_load_start','boards':BOARD_COUNT,
              'visits_per_board':THROWS_PER_BOARD,'pool_size':POOL_SIZE,
              'timeout_seconds':TIMEOUT_SECONDS},ensure_ascii=False),flush=True)
        async def watch_progress():
            while True:
                await asyncio.sleep(30)
                print(json.dumps({'phase':'http_load_progress',
                    'elapsed_seconds':round(time.perf_counter()-run_start,1),
                    'saved_via_http':sum(per_board_counts),
                    'target':BOARD_COUNT*THROWS_PER_BOARD,
                    'minimum_board_visits':min(per_board_counts),
                    'maximum_board_visits':max(per_board_counts),
                    'unexpected_statuses':len(errors)},ensure_ascii=False),flush=True)

        monitor = asyncio.create_task(watch_progress())
        try:
            await asyncio.wait_for(
                asyncio.gather(*(board_job_no_race(i) for i in range(BOARD_COUNT))),
                timeout=TIMEOUT_SECONDS)
        except TimeoutError:
            print(json.dumps({'phase':'http_load_timeout',
                'completed_visits':sum(per_board_counts),
                'target_visits':BOARD_COUNT*THROWS_PER_BOARD,
                'per_board':per_board_counts,
                'http_status_counts':dict(status_counts)},ensure_ascii=False),flush=True)
            raise
        finally:
            monitor.cancel()
            with suppress(asyncio.CancelledError):
                await monitor

        h={'Cookie':f'{api.COOKIE}={board_job_no_race.token}'}
        async with aiohttp.ClientSession(trust_env=False) as session:
            await post(session,f'/dart/v2/api/matches/{extra}/start',{'board_id':1,'starter':0},expected=409,headers=h)
            target=f'/dart/v2/api/matches/{matches[0]}/throw'
            race_statuses=[]
            await asyncio.gather(*[
                post(session,target,{'points':10,'darts':3,'version':THROWS_PER_BOARD},
                     expected=None,headers=h,capture_statuses=race_statuses)
                for _ in range(2)
            ])
            if sorted(race_statuses)!=[200,409]:
                errors.append({'problem':'Versionskonflikt nicht sicher behandelt',
                               'received_statuses':race_statuses})

        async with pool.acquire() as conn:
            row=await conn.fetchrow('''SELECT count(*) AS matches,
              count(*) FILTER(WHERE status='running') AS running,
              count(DISTINCT board_id) AS boards,
              sum(state_version)::int AS versions
              FROM stingrays_app.matches WHERE competition_id=$1 AND board_id IS NOT NULL''',cid)
            recorded=await conn.fetchval('''SELECT count(*) FROM stingrays_app.throws WHERE match_id=ANY($1::uuid[])''',matches)
            revised=await conn.fetchval('''SELECT count(*) FROM stingrays_app.match_revisions WHERE match_id=ANY($1::uuid[])''',matches)
            stored_ledger=await conn.fetch('''SELECT board_id,state_version,jsonb_array_length(state->'visits') AS visits
                                      FROM stingrays_app.matches WHERE id=ANY($1::uuid[])''',matches)

        want_visits=BOARD_COUNT*THROWS_PER_BOARD+1  # one successful race write
        assertions={
          '22 running games':row['running']==22,
          '22 unique boards':row['boards']==22,
          'all visits archived':recorded==want_visits,
          'all revisions present':revised==want_visits,
          'exactly one concurrent stale write accepted':row['versions']==want_visits,
          'per-board counters consistent':all(r['state_version']==r['visits'] for r in stored_ledger),
          'HTTP statuses expected':not errors,
          'exactly two intentional conflicts':status_counts[409]==2,
        }
        report={'mode':'echte HTTP-Endpunkte / echte Neon-Testbranch-Datenbank',
                'testbranch_guard':EXPECTED_SENTINEL,
                'run_prefix':PREFIX,
                'boards':BOARD_COUNT,
                'visits_per_board':THROWS_PER_BOARD,
                'test_pool_max':POOL_SIZE,
                'per_board_visits':per_board_counts,
                'throw_requests':BOARD_COUNT*THROWS_PER_BOARD+2,
                'requests_total':sum(status_counts.values()),
                'status_counts':dict(status_counts),
                'p50_ms':percentile(timings,.5),
                'p95_ms':percentile(timings,.95),
                'p99_ms':percentile(timings,.99),
                'wall_seconds':round(time.perf_counter()-run_start,2),
                'assertions':assertions,
                'failures':errors[:5],
                'note':'lokaler GitHub-Testjob gegen echten Neon-Testbranch; kein öffentlich erreichbarer Dienst'}
        print(json.dumps(report,indent=2,ensure_ascii=False),flush=True)
        if not all(assertions.values()):raise SystemExit(1)
    finally:
        if server is not None:await server.close()
        await pool.close()


if __name__ == '__main__':asyncio.run(main())
