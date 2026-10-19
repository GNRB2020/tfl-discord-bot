import asyncio, importlib.util, os, sys, types
from pathlib import Path
from unittest.mock import patch
from aiohttp import web
stub=types.ModuleType('dart_engine')
stub.possible_checkout_darts=lambda n: [1,2,3] if n in (40,50) else ([3] if n==170 else [])
stub.Match=type('Match',(),{'__init__':lambda self,r,n: None})
stub.Rules=type('Rules',(),{'__init__':lambda self,**kw:None})
sys.modules['dart_engine']=stub
spec=importlib.util.spec_from_file_location('phase6',str(Path(__file__).parent/'dart_render_preview.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Req:
    def __init__(self,game='',data=None,token='t'):
        self.headers={'X-Dart-Game-ID':game}
        self.cookies={'stingrays_session':token}
        self.host='host';self.scheme='https';self.data=data or {}
    async def json(self):return self.data
async def test():
    m.SESSIONS['t']=('Stingrays',99999999999)
    async def new(name):
        resp=await m.new_match(Req(data={'kind':'sau','a':name,'rounds':2}))
        import json
        return json.loads(resp.text)
    a=await new('A');b=await new('B')
    assert a['game_id']!=b['game_id']
    ga=a['game_id'];gb=b['game_id']
    for idx in range(10):
        for j in range(4):
            resp=await m.throw(Req(ga,{'points':0}))
            assert resp.status==200
        if idx<9:
            resp=await m.next_sau(Req(ga))
            assert resp.status==200
    import json
    final=json.loads(resp.text)
    assert final['finished'] and final['result']['rounds']==10 and final['result']['sau']==10
    assert final['result']['checkouts']==0
    assert m.GAMES[gb]['marks']['sau']==0
    assert (await m.next_sau(Req(ga))).status==409
    try:
        await m.throw(Req(ga,{'points':20},token='other'))
        assert False, 'Unauthorized request must fail'
    except web.HTTPUnauthorized:
        pass
    print('OK: independent games, ten Sau marks, end report, cannot continue')
asyncio.run(test())
