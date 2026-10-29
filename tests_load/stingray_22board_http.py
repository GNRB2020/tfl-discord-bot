"""Reproduzierbarer HTTP-Lasttest der originalen Dartscorer-Handler.

Aufruf im Repository-Root: python tests_load/stingray_22board_http.py

Keine externe Verbindung: echte aiohttp-Handler, isolierte In-Memory-DB nach
asyncpg-Protokoll, 22 unabhängige HTTP-Sessions; KEIN Neon-/Render-Benchmark.
"""
from __future__ import annotations
import asyncio
import json
import pathlib
import statistics
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from uuid import uuid5, NAMESPACE_DNS
from unittest.mock import patch

from aiohttp import ClientSession, web
from aiohttp.test_utils import TestServer

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from test_stingray_http_parallel import MemoryPool, Connection  # noqa: E402
from stingrays_v2 import api  # noqa: E402


class SimulatedConnection(Connection):
    async def fetchrow(self, sql, *args):
        await asyncio.sleep(self.pool.latency)
        return await super().fetchrow(sql, *args)

    async def fetchval(self, sql, *args):
        await asyncio.sleep(self.pool.latency)
        return await super().fetchval(sql, *args)

    async def fetch(self, sql, *args):
        await asyncio.sleep(self.pool.latency)
        return await super().fetch(sql, *args)

    async def execute(self, sql, *args):
        await asyncio.sleep(self.pool.latency)
        return await super().execute(sql, *args)


class Lease:
    def __init__(self, pool):
        self.pool = pool

    async def __aenter__(self):
        start = time.perf_counter()
        await self.pool.slots.acquire()
        self.pool.waits_ms.append((time.perf_counter() - start) * 1000)
        self.pool.active += 1
        self.pool.peak = max(self.pool.peak, self.pool.active)
        self.db = SimulatedConnection(self.pool)
        return self.db

    async def __aexit__(self, *args):
        try:
            await self.db.release()
        finally:
            self.pool.active -= 1
            self.pool.slots.release()


class BoundedMemoryPool(MemoryPool):
    def __init__(self, connections, latency):
        super().__init__(count=24)
        self.slots = asyncio.Semaphore(connections)
        self.latency = latency
        self.waits_ms = []
        self.active = 0
        self.peak = 0

    def acquire(self):
        return Lease(self)


def percentile(vals, q):
    if not vals:
        return 0
    a = sorted(vals)
    pos = (len(a) - 1) * q
    lo = int(pos)
    return round(a[lo] + (a[min(lo+1, len(a)-1)] - a[lo]) * (pos - lo), 2)


async def exercise(connections=3, latency_ms=2, throws_per_board=35):
    pool = BoundedMemoryPool(connections, latency_ms / 1000.0)
    ids = list(pool.matches)[:22]
    calls = Counter()
    latencies = []
    issues = []
    sessions = []

    async def actor_for(req, minimum=None, allow_change=False):
        cookie = req.cookies.get(api.COOKIE, '')
        if not cookie.startswith('loadtest-session-'):
            raise web.HTTPUnauthorized()
        return {'id':uuid5(NAMESPACE_DNS,cookie),'role':'tournament','player_id':None}

    app = web.Application()
    app.add_routes([
        web.post('/matches/{mid}/start', api.start_match),
        web.post('/matches/{mid}/throw', api.throw),
    ])
    app['stingrays_pool'] = pool
    server = TestServer(app, host='127.0.0.1', port=0)
    await server.start_server()

    async def post(session, path, data, expected=200):
        t0 = time.perf_counter()
        try:
            async with session.post(server.make_url(path), json=data) as resp:
                status = resp.status
                raw = await resp.text()
        except Exception as exc:
            status = 'exception'
            raw = str(exc)
        elapsed = (time.perf_counter() - t0) * 1000
        calls[str(status)] += 1
        if status == 200:
            latencies.append(elapsed)
        if status != expected:
            issues.append({'path':path,'status':status,'expected':expected,'message':raw[:200]})
        try:
            return json.loads(raw)
        except (ValueError,TypeError):
            return {}

    async def board_task(i):
        mid = ids[i]
        token = f'loadtest-session-{i+1}'
        headers = {'Cookie':f'{api.COOKIE}={token}'}
        session = ClientSession(headers=headers, trust_env=False)
        sessions.append(session)
        try:
            start = await post(session, f'/matches/{mid}/start', {'board_id':i+1,'starter':0})
            version = start.get('version')
            for n in range(throws_per_board):
                if version is None:
                    issues.append({'board':i+1,'problem':'Startantwort enthält keine Version'})
                    break
                ans = await post(session,f'/matches/{mid}/throw', {'points':10,'darts':3,'version':version})
                version = ans.get('version')
        finally:
            await session.close()

    start_time = time.perf_counter()
    try:
        with patch.object(api, 'actor', side_effect=actor_for):
            await asyncio.wait_for(asyncio.gather(*(board_task(i) for i in range(22))),timeout=100)
        elapsed = time.perf_counter() - start_time
    finally:
        await asyncio.gather(*(s.close() for s in sessions))
        await server.close()

    expected_visits = 22 * throws_per_board
    actual_visits = len(pool.visits)
    revisions = len(pool.revisions)
    versions = [pool.matches[mid]['state_version'] for mid in ids]
    distinct_boards = len({pool.matches[mid]['board_id'] for mid in ids})
    assert not issues, issues[:5]
    assert actual_visits == revisions == expected_visits, (actual_visits,revisions,expected_visits)
    assert versions == [throws_per_board]*22, versions
    assert distinct_boards == 22
    assert pool.active == 0
    return {
        'test': 'Lokale HTTP-Handler mit simulierter asyncpg-Verbindung',
        'utc': datetime.now(timezone.utc).isoformat(),
        'boards': 22,
        'independent_sessions': 22,
        'throws_per_board': throws_per_board,
        'simulated_connection_pool': connections,
        'artificial_sql_latency_ms_per_operation': latency_ms,
        'http_requests': sum(calls.values()),
        'status_counts': dict(calls),
        'archived_visits': actual_visits,
        'revisions': revisions,
        'distinct_boards': distinct_boards,
        'peak_db_connections': pool.peak,
        'wall_seconds': round(elapsed,3),
        'requests_per_second': round(sum(calls.values())/elapsed,1),
        'http_latency_ms': {'p50':percentile(latencies,0.50),
                            'p95':percentile(latencies,0.95),
                            'p99':percentile(latencies,0.99),
                            'max':round(max(latencies),2)},
        'pool_wait_ms': {'p50':percentile(pool.waits_ms,0.50),
                         'p95':percentile(pool.waits_ms,0.95),
                         'p99':percentile(pool.waits_ms,0.99)},
        'failed_expected_requests':len(issues),
    }


if __name__ == '__main__':
    async def main():
        import argparse
        p = argparse.ArgumentParser()
        p.add_argument('--connections', type=int, default=3)
        p.add_argument('--latency-ms', type=float, default=2)
        p.add_argument('--throws', type=int, default=35)
        args = p.parse_args()
        result = await exercise(args.connections,args.latency_ms,args.throws)
        print(json.dumps(result,indent=2,ensure_ascii=False))
    asyncio.run(main())
