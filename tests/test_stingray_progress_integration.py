"""In-memory DB-adapter integration for the REAL progress() orchestration.

This exercises the production SQL branching and persistence calls without
connecting to, creating, or modifying production Neon data.
"""
import json
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from uuid import uuid4
from stingrays_v2.rules import round_robin, bracket_pairs
from stingrays_v2.tournament_automation import progress
from stingrays_v2.api import advance_knockout


class _Context:
    def __init__(self, db): self.db=db
    async def __aenter__(self): return self.db
    async def __aexit__(self, *args): return False


class FakeDB:
    def __init__(self, kind, players, *, grouped=False, follow_format='single_ko'):
        self.cid=uuid4()
        self.players=list(players)
        cfg={'auto_tournament':True,'format':'groups' if grouped else kind,
             'training_match':{'mode':'legs','max_legs':5,'start_score':501,'allow_draw':False},
             'ko_match':{'mode':'legs','max_legs':5,'start_score':501,'allow_draw':False},
             'follow':grouped,'qualifiers':'1','best_third_count':0,
             'follow_format':follow_format,'round_lengths':{},'consolation':False,
             'follow_group_count':2,'consolation_group_count':2,'third_place':False}
        self.comp={'id':self.cid,'kind':'training_tournament','status':'active','rules':json.dumps(cfg)}
        self.phases=[];self.groups=[];self.members={};self.matches=[]
        first=uuid4()
        fmt='groups' if grouped else kind
        self.phases.append({'id':first,'phase_order':1,'kind': 'groups' if grouped else 'knockout',
                            'name':'Vorrunde','status':'open','rules':json.dumps({
                                'format':fmt,'stage':'preliminary','participants':[str(x) for x in self.players],
                                'match_rules':cfg['training_match'],
                                'bracket_released':True,
                                'bye_players':[]})})
        if grouped:
            for k in range(0,len(self.players),3):
                group={'id':uuid4(),'name':'Gruppe '+str(k//3+1),'sort_order':k//3+1,'phase_id':first}
                self.groups.append(group)
                people=self.players[k:k+3];self.members[group['id']]=people
                for rnd,a,b in round_robin(people):
                    self._add_match(first,a,b,rnd,None,group['id'],status='finished')
        else:
            pairs=bracket_pairs(self.players)
            byes=[p for a,b in pairs for p in (a,b) if p is not None and (a is None or b is None)]
            self.phases[0]['rules']=json.dumps({**json.loads(self.phases[0]['rules']),'bye_players':[str(x) for x in byes]})
            for i,(a,b) in enumerate(pairs,1):
                if a is not None and b is not None:
                    self._add_match(first,a,b,1,i,status='finished')

    def transaction(self):return _Context(self)
    def acquire(self):return _Context(self)
    def _add_match(self,phase,p1,p2,rnd,pos,group=None,status='open',rules=None):
        m={'id':uuid4(),'phase_id':phase,'competition_id':self.cid,'group_id':group,
           'player1_id':p1,'player2_id':p2,'round_number':rnd,'bracket_position':pos,
           'status':status,'legs1':3 if status=='finished' else None,
           'legs2':1 if status=='finished' else None,'sets1':None,'sets2':None,
           'rules':json.dumps(rules or {'mode':'legs','max_legs':5})}
        self.matches.append(m)
        return m

    async def fetchrow(self, sql,*args):
        q=sql.lower()
        if 'from stingrays_app.phases p' in q and 'join stingrays_app.competitions c' in q:
            phase=next(p for p in self.phases if p['id']==args[0])
            return {**phase,'competition_id':self.cid,'competition_kind':self.comp['kind'],
                    'competition_rules':self.comp['rules']}
        if 'from stingrays_app.competitions' in q:
            return dict(self.comp)
        if 'from stingrays_app.phases' in q and 'phase_order=$2' in q:
            return next((dict(p) for p in self.phases if p['phase_order']==args[1]),None)
        raise AssertionError('Unexpected fetchrow '+sql[:110])

    async def fetch(self,sql,*args):
        q=sql.lower()
        if 'from stingrays_app.phases' in q:
            if 'select id,kind,status' in q:
                return [{'id':p['id'],'kind':p['kind'],'status':p['status']} for p in self.phases]
            return [dict(p) for p in sorted(self.phases,key=lambda p:p['phase_order'])]
        if 'from stingrays_app.groups' in q:
            return [dict(g) for g in sorted(self.groups,key=lambda g:g['sort_order']) if g['phase_id']==args[0]]
        if 'from stingrays_app.group_members' in q:
            return [{'player_id':p} for p in self.members[args[0]]]
        if 'from stingrays_app.matches' in q:
            if 'where group_id=$1' in q:
                return [dict(m) for m in self.matches if m['group_id']==args[0]]
            ms=[dict(m) for m in self.matches if m['phase_id']==args[0]]
            if 'round_number=$2' in q:ms=[m for m in ms if m['round_number']==args[1]]
            return sorted(ms,key=lambda m:(m['round_number'],m['bracket_position'] or 0))
        raise AssertionError('Unexpected fetch '+sql[:120])

    async def fetchval(self,sql,*args):
        q=sql.lower()
        if 'insert into stingrays_app.phases' in q:
            ph={'id':uuid4(),'phase_order':args[3],'name':args[1],'kind':args[2],
                'status':'open','rules':args[4]}
            self.phases.append(ph)
            return ph['id']
        if 'insert into stingrays_app.groups' in q:
            g={'id':uuid4(),'phase_id':args[0],'name':args[1],'sort_order':args[2]}
            self.groups.append(g);self.members[g['id']]=[]
            return g['id']
        if 'select exists' in q:return False
        if 'from stingrays_app.matches' in q:
            ms=[m for m in self.matches if m['phase_id']==args[0]]
            if 'max(round_number)' in q:
                return max((m['round_number'] for m in ms),default=None)
            if "status<>'finished'" in q:return sum(m['status']!='finished' for m in ms)
            return len(ms)
        if 'from stingrays_app.phases' in q:
            return sum(p['status']!='closed' for p in self.phases)
        raise AssertionError('Unexpected fetchval '+sql[:120])

    async def execute(self,sql,*args):
        q=sql.lower()
        if 'update stingrays_app.phases' in q:
            ph=next(p for p in self.phases if p['id']==args[0])
            if "status='closed'" in q:ph['status']='closed'
            elif 'set rules=rules ||' in q:
                ph['rules']=json.dumps({**json.loads(ph['rules']),**json.loads(args[1])})
            elif "status='open'" in q:
                ph.update({'name':args[1],'kind':args[2],'status':'open','rules':args[3]})
            else:raise AssertionError('Unknown phase update '+q[:110])
            return 'UPDATE 1'
        if 'update stingrays_app.competitions' in q:
            self.comp['status']='finished';return 'UPDATE 1'
        if 'insert into stingrays_app.matches' in q:
            if 'group_id' in q:
                _,ph,gid,rnd,p1,p2,_=args
                self._add_match(ph,p1,p2,rnd,None,gid,rules=json.loads(args[-1]))
            else:
                if len(args)==6:
                    _,ph,pos,p1,p2,_=args; rnd=1
                else:
                    _,ph,rnd,pos,p1,p2,_=args
                self._add_match(ph,p1,p2,rnd,pos,rules=json.loads(args[-1]))
            return 'INSERT 1'
        if 'insert into stingrays_app.group_members' in q:
            self.members[args[0]].append(args[2]);return 'INSERT 1'
        raise AssertionError('Unexpected execute '+sql[:130])


class ProgressIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_groups_qualify_and_finish_single_ko(self):
        db=FakeDB('groups',[uuid4() for _ in range(12)],grouped=True)
        with patch('stingrays_v2.tournament_automation.pool',return_value=db):
            await progress(None,db.cid)
            stages=[p for p in db.phases if p['phase_order']==2]
            self.assertEqual(len(stages),1)
            ph=stages[0]
            self.assertEqual(len([m for m in db.matches if m['phase_id']==ph['id']]),2)
            self.assertFalse(json.loads(ph['rules'])['bracket_released'])
            # Premature rechecks may not create duplicates or release the draw.
            await progress(None,db.cid)
            self.assertEqual(len([m for m in db.matches if m['phase_id']==ph['id']]),2)
            ph['rules']=json.dumps({**json.loads(ph['rules']),'bracket_released':True})
            for _ in range(6):
                open_games=[m for m in db.matches if m['phase_id']==ph['id'] and m['status']=='open']
                if not open_games:break
                for m in open_games:m.update(status='finished',legs1=3,legs2=1)
                await progress(None,db.cid)
            self.assertEqual(ph['status'],'closed')
            self.assertEqual(db.comp['status'],'finished')
            self.assertEqual(len([m for m in db.matches if m['phase_id']==ph['id']]),3)
            await progress(None,db.cid)
            self.assertEqual(len([m for m in db.matches if m['phase_id']==ph['id']]),3)

    async def test_groups_qualify_and_finish_double_ko(self):
        db=FakeDB('groups',[uuid4() for _ in range(15)],grouped=True,follow_format='double_ko')
        with patch('stingrays_v2.tournament_automation.pool',return_value=db):
            await progress(None,db.cid)
            ph=next(p for p in db.phases if p['phase_order']==2)
            self.assertEqual(json.loads(ph['rules'])['format'],'double_ko')
            self.assertFalse(json.loads(ph['rules'])['bracket_released'])
            ph['rules']=json.dumps({**json.loads(ph['rules']),'bracket_released':True})
            for _ in range(32):
                ms=[m for m in db.matches if m['phase_id']==ph['id'] and m['status']=='open']
                for m in ms:m.update(status='finished',legs1=3,legs2=1)
                await progress(None,db.cid)
                if db.comp['status']=='finished':break
            self.assertEqual(db.comp['status'],'finished')
            ko=[m for m in db.matches if m['phase_id']==ph['id']]
            self.assertGreaterEqual(len(ko),4)
            self.assertLessEqual(len(ko),9)

    async def test_group_wildcard_tie_requires_decision(self):
        from aiohttp import web
        db=FakeDB('groups',[uuid4() for _ in range(12)],grouped=True)
        config=json.loads(db.comp['rules']);config['best_third_count']=2
        db.comp['rules']=json.dumps(config)
        with patch('stingrays_v2.tournament_automation.pool',return_value=db):
            with self.assertRaises(web.HTTPConflict) as exc:
                await progress(None,db.cid)
            self.assertIn('manuelle Entscheidung',exc.exception.text)
            self.assertEqual(len(db.phases),1)

    async def test_30_player_cup_six_wildcards_to_final(self):
        from aiohttp import web
        from stingrays_v2.rules import rank_rows
        db=FakeDB('groups',[uuid4() for _ in range(30)],grouped=True)
        db.comp['kind']='cup'
        cfg=json.loads(db.comp['rules']);cfg['best_third_count']=6
        db.comp['rules']=json.dumps(cfg)
        with patch('stingrays_v2.tournament_automation.pool',return_value=db):
            with self.assertRaises(web.HTTPConflict):
                await progress(None,db.cid)
            manual=[]
            for group in db.groups:
                ranks=rank_rows([m for m in db.matches if m['group_id']==group['id']],db.members[group['id']])
                manual.append(ranks[1]['player_id'])
            cfg['best_third_manual_ids']=[str(p) for p in manual[:6]]
            db.comp['rules']=json.dumps(cfg)
            await progress(None,db.cid)
            ph=next(p for p in db.phases if p['phase_order']==2)
            self.assertEqual(len(json.loads(ph['rules'])['participants']),16)
            first=[m for m in db.matches if m['phase_id']==ph['id']]
            self.assertEqual(len(first),8)
            for m in first:
                rules=json.loads(m['rules'])
                self.assertEqual(rules['mode'],'sets')
                self.assertEqual(rules['best_of_sets'],5)
                self.assertEqual(rules['best_of_legs_per_set'],5)
            ph['rules']=json.dumps({**json.loads(ph['rules']),'bracket_released':True})
            for _ in range(5):
                open_games=[m for m in db.matches if m['phase_id']==ph['id'] and m['status']=='open']
                if not open_games:break
                for m in open_games:m.update(status='finished',legs1=3,legs2=1,sets1=3,sets2=1)
                await progress(None,db.cid)
            self.assertEqual(ph['status'],'closed')
            self.assertEqual(db.comp['status'],'finished')
            self.assertEqual(len([m for m in db.matches if m['phase_id']==ph['id']]),15)

    async def test_manual_ko_advance_matches_production_planner(self):
        from aiohttp import web
        db=FakeDB('single_ko',[uuid4() for _ in range(5)])
        ph=db.phases[0]
        req=SimpleNamespace(match_info={'pid':str(ph['id'])})
        async def stub(*args,**kwargs):return {'id':uuid4(),'role':'admin'}
        async def empty(*args,**kwargs):return {}
        with patch('stingrays_v2.api.actor',stub),patch('stingrays_v2.api.body',empty), \
             patch('stingrays_v2.api.require_manager',empty), \
             patch('stingrays_v2.api.pool',return_value=db):
            async def bad_rules(*args,**kwargs):return {'rules':{'max_legs':6,'allow_draw':True}}
            with patch('stingrays_v2.api.body',bad_rules),self.assertRaises(web.HTTPBadRequest):
                await advance_knockout(req)
            self.assertEqual(len(db.matches),1)
            r=await advance_knockout(req)
            self.assertEqual(json.loads(r.text)['created'],2)
            with self.assertRaises(web.HTTPConflict):
                await advance_knockout(req)  # Previous manual button must not duplicate games.
            for m in db.matches:
                if m['status']=='open':m.update(status='finished',legs1=3,legs2=1)
            r=await advance_knockout(req)
            self.assertEqual(json.loads(r.text)['created'],1)
            for m in db.matches:
                if m['status']=='open':m.update(status='finished',legs1=3,legs2=1)
            r=await advance_knockout(req)
            self.assertTrue(json.loads(r.text)['completed'])
            self.assertEqual(ph['status'],'closed')
            self.assertEqual(len(db.matches),4)

    async def test_double_ko_odd_participants_finish(self):
        db=FakeDB('double_ko',[uuid4() for _ in range(7)])
        with patch('stingrays_v2.tournament_automation.pool',return_value=db):
            for _ in range(35):
                open_games=[m for m in db.matches if m['status']=='open']
                for m in open_games:m.update(status='finished',legs1=3,legs2=1)
                await progress(None,db.cid)
                if db.comp['status']=='finished':break
            self.assertEqual(db.comp['status'],'finished')
            self.assertEqual(db.phases[0]['status'],'closed')
            self.assertGreaterEqual(len(db.matches),6)
            self.assertLessEqual(len(db.matches),13)


if __name__=='__main__':unittest.main()
