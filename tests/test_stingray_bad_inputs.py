"""HTTP regression checks for malformed data, without Neon or production access."""
import asyncio
import unittest
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from stingrays_v2 import api
from test_stingray_http_parallel import MemoryPool


class InvalidPayloadTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.pool = MemoryPool(count=1)
        self.mid = list(self.pool.matches)[0]
        self.actor_patcher = patch('stingrays_v2.api.actor', return_value=self.pool.account)
        self.actor_patcher.start()
        app = web.Application()
        app['stingrays_pool'] = self.pool
        app.add_routes([
            web.post('/matches/{mid}/start', api.start_match),
            web.post('/matches/{mid}/throw', api.throw),
        ])
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.actor_patcher.stop()

    async def test_invalid_board_number_returns_400(self):
        for bad in ('abc', '1.5', 1.5, 1.0, None, True, 23, -4):
            if bad is None: continue  # None means intentionally unassigned
            with self.subTest(bad=bad):
                response = await self.client.post(f'/matches/{self.mid}/start',json={'board_id':bad})
                self.assertEqual(response.status,400,await response.text())
                await response.release()
        self.assertEqual(self.pool.matches[self.mid]['status'], 'open')

    async def test_invalid_starter_returns_400_without_starting(self):
        for bad in ('unknown', [], True, 1.5, 9):
            with self.subTest(bad=bad):
                response = await self.client.post(f'/matches/{self.mid}/start',json={'board_id':1,'starter':bad})
                self.assertEqual(response.status,400,await response.text())
                await response.release()
        self.assertEqual(self.pool.matches[self.mid]['status'],'open')

    async def test_invalid_throw_version_returns_400(self):
        response = await self.client.post(f'/matches/{self.mid}/start',json={'board_id':1,'starter':0})
        self.assertEqual(response.status,200)
        await response.release()
        for bad in ('abc', '', None, True, 0.5, {}):
            with self.subTest(bad=bad):
                response = await self.client.post(f'/matches/{self.mid}/throw',json={'points':60,'darts':3,'version':bad})
                self.assertEqual(response.status,400,await response.text())
                await response.release()
        self.assertEqual(self.pool.matches[self.mid]['state_version'],0)
        self.assertEqual(len(self.pool.visits),0)


if __name__ == '__main__':unittest.main()
