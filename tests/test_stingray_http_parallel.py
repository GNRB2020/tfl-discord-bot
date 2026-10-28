"""HTTP-level 22-board start and concurrent throw checks for Stingrays V2.

Runs the REAL start_match/throw aiohttp handlers with an isolated asyncpg
protocol fake. Neon/production are never contacted. Database uniqueness is
independently exercised on a Neon test branch, not reimplemented here.
"""
import asyncio
import json
import unittest
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from stingrays_v2 import api


class MemoryPool:
    def __init__(self, count=24):
        self.account = {'id': uuid4(), 'role': 'admin', 'player_id': None}
        self.matches = {}
        self.match_locks = {}
        self.board_locks = {board: asyncio.Lock() for board in range(1,23)}
        self.claims = {}
        self.enabled_boards=set(range(1,23))
        self.legs = {}
        self.visits = []
        self.revisions = []
        rules={'mode':'legs','max_legs':5,'start_score':501,'allow_draw':False,'double_out':True}
        for _ in range(count):
            mid=uuid4()
            self.matches[mid]={
                'id':mid,'competition_id':uuid4(),'kind':'league','competition_status':'active',
                'player1':'A','player2':'B','player1_id':uuid4(),'player2_id':uuid4(),
                'phase_id':None,'ends_at':None,'rules':rules,'state':{},'state_version':0,
                'status':'open','started_at':None,'board_id':None,
            }
            self.match_locks[mid]=asyncio.Lock()

    def acquire(self):
        return PoolLease(self)


class PoolLease:
    def __init__(self,pool):self.pool=pool
    async def __aenter__(self):
        self.db=Connection(self.pool)
        return self.db
    async def __aexit__(self,*args):
        await self.db.release()


class Connection:
    def __init__(self,pool):
        self.pool=pool
        self.held=[]
    async def release(self):
        for lock in reversed(self.held):lock.release()
        self.held=[]
    @asynccontextmanager
    async def transaction(self):
        try:yield self
        finally:await self.release()
    async def _lock(self,lock):
        await lock.acquire()
        self.held.append(lock)
        await asyncio.sleep(0)  # test scheduling between independent requests
    async def fetchrow(self,sql,*args):
        low=sql.lower()
        if 'from stingrays_app.matches m' in low and 'for update of m' in low:
            mid=args[0]
            await self._lock(self.pool.match_locks[mid])
            return dict(self.pool.matches[mid])
        if 'from stingrays_app.boards' in low:
            assert 'for update' in low, 'Board reservation needs row lock'
            board=args[0]
            await self._lock(self.pool.board_locks[board])
            return {'enabled':board in self.pool.enabled_boards}
        if 'from stingrays_app.match_claims' in low:
            return self.pool.claims.get(args[0])
        if 'insert into stingrays_app.match_legs' in low:
            mid,leg_num,starter=args
            key=(mid,leg_num)
            if key not in self.pool.legs:
                self.pool.legs[key]={'id':uuid4(),'match_id':mid,'winner_id':None}
            return {'id':self.pool.legs[key]['id']}
        raise AssertionError('Unmocked fetchrow: '+low[:120])
    async def fetchval(self,sql,*args):
        low=sql.lower()
        if 'from stingrays_app.matches' in low and 'board_id=$1' in low:
            board,except_mid=args
            return next((m['id'] for m in self.pool.matches.values()
                        if m['board_id']==board and m['status']=='running' and m['id']!=except_mid),None)
        raise AssertionError('Unmocked fetchval: '+low[:120])
    async def fetch(self,sql,*args):
        if 'from stingrays_app.match_legs' in sql.lower():return []
        raise AssertionError('Unmocked fetch: '+sql[:120])
    async def execute(self,sql,*args):
        low=sql.lower()
        if 'insert into stingrays_app.match_claims' in low:
            mid,account,device,thash=args
            self.pool.claims[mid]={'account_id':account,'token_hash':thash,
                                   'lease_until':datetime.now(timezone.utc)+timedelta(minutes=45)}
        elif 'update stingrays_app.matches' in low and "status='running'" in low:
            mid,board,state=args
            m=self.pool.matches[mid]
            if any(other['id']!=mid and other['status']=='running' and other['board_id']==board
                   for other in self.pool.matches.values()):
                raise AssertionError('Unique board violation')
            m.update(status='running',board_id=board,state=json.loads(state))
        elif 'insert into stingrays_app.throws' in low:
            self.pool.visits.append(args)
        elif 'update stingrays_app.match_legs set winner_id' in low:
            pass
        elif 'update stingrays_app.matches set state=' in low:
            mid,state,done,*rest=args
            self.pool.matches[mid].update(state=json.loads(state),status='finished' if done else 'running')
            self.pool.matches[mid]['state_version']+=1
        elif 'insert into stingrays_app.match_revisions' in low:
            self.pool.revisions.append(args)
        elif 'update stingrays_app.match_claims set lease_until' in low:
            pass
        else:
            raise AssertionError('Unmocked execute: '+low[:145])
        return 'OK'


class HttpParallelTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.pool=MemoryPool()
        self.api_patcher=patch('stingrays_v2.api.actor',return_value=self.pool.account)
        self.api_patcher.start()
        app=web.Application()
        app.add_routes([
            web.post('/matches/{mid}/start',api.start_match),
            web.post('/matches/{mid}/throw',api.throw),
        ])
        app['stingrays_pool']=self.pool
        self.client=TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.api_patcher.stop()

    async def test_22_boards_at_once_and_reject_duplicate(self):
        ids=list(self.pool.matches)
        requests=[self.client.post(f'/matches/{mid}/start',json={'board_id':i+1,'starter':0})
                  for i,mid in enumerate(ids[:22])]
        results=await asyncio.gather(*requests)
        try:
            self.assertEqual([r.status for r in results],[200]*22)
        finally:
            await asyncio.gather(*(r.read() for r in results))
        self.assertEqual(len([m for m in self.pool.matches.values() if m['status']=='running']),22)
        self.assertEqual({m['board_id'] for m in self.pool.matches.values() if m['status']=='running'},set(range(1,23)))
        attempt=await self.client.post(f'/matches/{ids[22]}/start',json={'board_id':1,'starter':0})
        self.assertEqual(attempt.status,409)
        self.assertIn('Board bereits belegt',await attempt.text())

    async def test_disabled_board_does_not_start_match(self):
        self.pool.enabled_boards.remove(22)
        mid=list(self.pool.matches)[0]
        result=await self.client.post(f'/matches/{mid}/start',json={'board_id':22})
        self.assertEqual(result.status,409)
        self.assertIn('Board deaktiviert',await result.text())
        self.assertEqual(self.pool.matches[mid]['status'],'open')

    async def test_two_simultaneous_starts_same_board_return_409(self):
        ids=list(self.pool.matches)
        responses=await asyncio.gather(*[
            self.client.post(f'/matches/{mid}/start',json={'board_id':1,'starter':0})
            for mid in ids[:2]
        ])
        try:
            self.assertEqual(sorted(r.status for r in responses),[200,409])
        finally:
            await asyncio.gather(*(r.read() for r in responses))
        running=[m for m in self.pool.matches.values() if m['status']=='running']
        self.assertEqual(len(running),1)
        self.assertEqual(running[0]['board_id'],1)

    async def test_22_parallel_throws_update_every_match_once(self):
        ids=list(self.pool.matches)[:22]
        starts=await asyncio.gather(*[
            self.client.post(f'/matches/{mid}/start',json={'board_id':i+1,'starter':0})
            for i,mid in enumerate(ids)
        ])
        self.assertEqual([r.status for r in starts],[200]*22)
        await asyncio.gather(*(r.read() for r in starts))
        responses=await asyncio.gather(*[
            self.client.post(f'/matches/{mid}/throw',json={'points':60,'darts':3,'version':0})
            for mid in ids
        ])
        try:
            self.assertEqual([r.status for r in responses],[200]*22)
        finally:
            await asyncio.gather(*(r.read() for r in responses))
        self.assertEqual(len(self.pool.visits),22)
        self.assertTrue(all(self.pool.matches[mid]['state_version']==1 for mid in ids))
        self.assertTrue(all(len(self.pool.matches[mid]['state']['visits'])==1 for mid in ids))

    async def test_two_simultaneous_throws_stale_version_rejected(self):
        mid=list(self.pool.matches)[0]
        start=await self.client.post(f'/matches/{mid}/start',json={'board_id':1,'starter':0})
        self.assertEqual(start.status,200)
        await start.read()
        data={'points':60,'darts':3,'version':0}
        responses=await asyncio.gather(*[
            self.client.post(f'/matches/{mid}/throw',json=data)
            for _ in range(2)
        ])
        try:
            self.assertEqual(sorted(r.status for r in responses),[200,409])
        finally:
            await asyncio.gather(*(r.read() for r in responses))
        self.assertEqual(self.pool.matches[mid]['state_version'],1)
        self.assertEqual(len(self.pool.visits),1)
        self.assertEqual(len(self.pool.matches[mid]['state']['visits']),1)


if __name__=='__main__':unittest.main()
