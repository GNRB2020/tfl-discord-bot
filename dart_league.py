"""Stingrays League restoration: persisted seasons, divisions, legacy scores and live X01.
Requires Google Sheet and existing Stingrays login. Admin mutations additionally require admin PIN.
"""
from __future__ import annotations
import asyncio, copy, hmac, os, secrets
from dataclasses import asdict
from datetime import datetime, timezone
from aiohttp import web
from dart_engine import Match, Rules, possible_checkout_darts
from dart_training_tournaments import _pack_match, _unpack_match
from sheets_connection import get_spreadsheet
import base64, json, zlib

SPREADSHEET_ID=os.getenv('DART_SPREADSHEET_ID','1DNlOzaOXzCDkZjoK_KU_ixhuQlwWPkcp4hVMQWNiHvs')
TAB='DART_LeagueSnapshots'
LEAGUES={}
LOCK=asyncio.Lock()

def _sheet():
 import gspread
 ss=get_spreadsheet(SPREADSHEET_ID)
 try:return ss.worksheet(TAB)
 except gspread.WorksheetNotFound:return ss.add_worksheet(title=TAB,rows=500,cols=4)

def _persist_sync(t):
 ws=_sheet();raw=json.dumps(t,ensure_ascii=False,separators=(',',':')).encode('utf-8')
 val=base64.b64encode(zlib.compress(raw,9)).decode('ascii')
 if len(val)>45000:raise ValueError('Liga-Snapshot zu groß für eine Tabellenzelle')
 cells=ws.get_all_values()
 if not cells:ws.update(range_name='A1:D1',values=[['league_id','updated_utc','snapshot','schema']]);cells=[['league_id','updated_utc','snapshot','schema']]
 row=next((i+1 for i,v in enumerate(cells) if v and v[0]==t['id']),len(cells)+1)
 ws.update(range_name=f'A{row}:D{row}',values=[[t['id'],datetime.now(timezone.utc).isoformat(),val,'1']],value_input_option='RAW')

def _load_sync():
 data={}
 for row in _sheet().get_all_values()[1:]:
  if len(row)<3 or not row[0]:continue
  d=json.loads(zlib.decompress(base64.b64decode(row[2])).decode('utf-8'))
  if d['id']!=row[0]:raise ValueError('Widersprüchliche Liga-ID im Sheet')
  data[d['id']]=d
 return data
async def restore_leagues():
 data=await asyncio.to_thread(_load_sync)
 async with LOCK:LEAGUES.update(data)
 print(f'[STINGRAYS LEAGUE] {len(data)} Ligen aus Google Sheets wiederhergestellt',flush=True)

def _pack(s):return copy.deepcopy(s)
def _now():return datetime.now(timezone.utc).isoformat(timespec='seconds')
def _get(lid):
 s=LEAGUES.get(lid)
 if not s or s.get('deleted'):raise web.HTTPNotFound(text='Liga nicht gefunden')
 return s

def _admin(data):
 pin=str(data.get('admin_pin',''))
 expected=os.environ.get('DART_ADMIN_PIN','')
 if len(expected)<10 or not hmac.compare_digest(pin,expected):raise web.HTTPForbidden(text='Admin-PIN erforderlich')

def _rounds(names,twice):
 arr=list(range(len(names)))
 if len(arr)%2:arr.append(None)
 result=[]
 for r in range(len(arr)-1):
  for j in range(len(arr)//2):
   a,b=arr[j],arr[-j-1]
   if a is None or b is None:continue
   if (r+j)%2:a,b=b,a
   result.append((r+1,a,b))
  arr=[arr[0],arr[-1],*arr[1:-1]]
 if twice:
  prev=result[:];result += [(r+len(arr)-1,b,a) for r,a,b in prev]
 return result

def _fixture(group,round_number,a,b,mode,best):
 return {'id':secrets.token_urlsafe(9),'group_id':group['id'],'round':round_number,'a':a,'b':b,
         'source':'open','legs':None,'sets':None,'game':None,'undo':None,'version':0,'starter':None,
         'entered_at':None,'import_note':'','mode':mode,'best_of':best}

def _table(s,g):
 names={p['id']:p['name'] for p in g['players']}; rows={pid:{'id':pid,'name':name,'played':0,'wins':0,'draws':0,'losses':0,'for':0,'against':0,'points':0} for pid,name in names.items()}
 for f in s['fixtures']:
  if f['group_id']!=g['id'] or f['legs'] is None:continue
  l,r=f['legs'];
  for pid,scored,conceded in [(f['a'],l,r),(f['b'],r,l)]:
   x=rows[pid];x['played']+=1;x['for']+=scored;x['against']+=conceded
   if scored>conceded:x['wins']+=1;x['points']+=s['points_win']
   elif scored==conceded:x['draws']+=1;x['points']+=s['points_draw']
   else:x['losses']+=1
 return sorted(rows.values(),key=lambda x:(-x['points'],-(x['for']-x['against']),-x['for'],x['name'].casefold()))

def _public(s):
 z={k:copy.deepcopy(v) for k,v in s.items() if k!='fixtures'}
 z['groups']=[{**g,'standings':_table(s,g)} for g in s['groups']]
 z['fixtures']=[{k:copy.deepcopy(v) for k,v in f.items() if k not in ('game','undo')}|{'status':'finished' if f['legs'] is not None else 'running' if f['game'] and f['game']['visits'] else 'open'} for f in s['fixtures']]
 return z

def _find(s,mid):
 f=next((f for f in s['fixtures'] if f['id']==mid),None)
 if not f:raise web.HTTPNotFound(text='Begegnung nicht gefunden')
 return f

def _match_state(s,f):
 if f['source']=='legacy':raise web.HTTPConflict(text='Übernommenes Ergebnis: kein historischer Scorer vorhanden')
 if f['game'] is None:
  names={p['id']:p['name'] for g in s['groups'] for p in g['players']}
  m=Match(Rules(start_score=s['start_score'],mode='legs',max_legs=f['best_of'],best_of_sets=f['best_of'],best_of_legs_per_set=5,allow_draw=f['best_of']%2==0),(names[f['a']],names[f['b']]))
 else:m=_unpack_match(f['game'])
 stats=m.summary()
 return {'id':f['id'],'version':f['version'],'kind':'x01','names':list(m.names),'remaining':m.remaining[:],
  'legs':m.legs[:],'sets':m.sets[:],'current':m.current,'done':m.done,'leg_number':m.leg_number,
  'rules':vars(m.rules),'can_checkout':possible_checkout_darts(m.remaining[m.current]) if not m.done and m.remaining[m.current]<=170 else [],
  'current_stats':stats['players'],'summary':stats if m.done else None,'starter':f['starter'],
  'history':[asdict(v) for v in m.visits],'can_undo':f['undo'] is not None,'started_at':f.get('started_at'),'finished_at':f.get('finished_at')}

async def listing(request):return web.json_response({'items':[{'id':s['id'],'name':s['name'],'created':s['created'],'status':s.get('status','active')} for s in LEAGUES.values() if not s.get('deleted')]})
async def detail(request):return web.json_response(_public(_get(request.match_info['lid'])))

async def create(request):
 data=await request.json();_admin(data)
 groups=data.get('groups',[])
 if not isinstance(groups,list) or not groups or len(groups)>12:return web.json_response({'error':'1 bis 12 Staffeln erforderlich'},status=400)
 mode=data.get('mode','double');best=int(data.get('best_of',5));start=int(data.get('start_score',501))
 if mode not in ('single','double') or best<1 or best>51 or start not in (301,501,701):return web.json_response({'error':'Ungültige Ligaregeln'},status=400)
 normalized=[];seen=set()
 for block in groups:
  name=str(block.get('name','')).strip()[:80]
  players=block.get('players',[])
  if not name or not isinstance(players,list) or not 2<=len(players)<=32:return web.json_response({'error':'Jede Staffel braucht 2–32 Spieler und einen Namen'},status=400)
  p=[]
  for item in players:
   display=str(item.get('name','')).strip()[:60]
   pid=str(item.get('id') or ('GUEST-'+secrets.token_urlsafe(10)))
   if not display or pid in seen:return web.json_response({'error':'Spieler fehlen oder kommen doppelt vor'},status=400)
   seen.add(pid);p.append({'id':pid,'name':display})
  normalized.append({'id':secrets.token_urlsafe(8),'name':name,'players':p})
 s={'id':secrets.token_urlsafe(12),'name':str(data.get('name','Stingray League')).strip()[:100], 'created':_now(),
    'status':'active','mode':mode,'best_of':best,'start_score':start,'points_win':int(data.get('points_win',2)),
    'points_draw':int(data.get('points_draw',1)),'groups':normalized,'fixtures':[]}
 for group in normalized:
  for r,a,b in _rounds(group['players'],mode=='double'):
   s['fixtures'].append(_fixture(group,r,group['players'][a]['id'],group['players'][b]['id'],'legs',best))
 async with LOCK:
  try:await asyncio.to_thread(_persist_sync,s)
  except Exception as e:return web.json_response({'error':f'Speicherung fehlgeschlagen: {e}'},status=503)
  LEAGUES[s['id']]=s
 return web.json_response(_public(s))

async def manual_result(request):
 data=await request.json();_admin(data)
 async with LOCK:
  current=_get(request.match_info['lid']);s=_pack(current);f=_find(s,request.match_info['mid'])
  if f['game'] is not None and f['game'].get('visits') and f['source']!='legacy':return web.json_response({'error':'Scorer-Spiel begonnen. Ergebnis nicht als Altbestand überschreiben'},status=409)
  try:a=int(data['a']);b=int(data['b'])
  except (KeyError,ValueError,TypeError):return web.json_response({'error':'Legergebnis fehlt'},status=400)
  if not 0<=a<=51 or not 0<=b<=51 or (a==b and f['best_of']%2) or max(a,b)>f['best_of'] or (f['best_of']%2 and max(a,b)!=(f['best_of']//2+1)):return web.json_response({'error':'Ungültiges Legergebnis'},status=400)
  f.update(source='legacy',legs=[a,b],sets=None,game=None,undo=None,entered_at=_now(),import_note=str(data.get('note',''))[:500]);f['version']+=1
  try:await asyncio.to_thread(_persist_sync,s)
  except Exception as e:return web.json_response({'error':f'Speicherung fehlgeschlagen: {e}'},status=503)
  LEAGUES[s['id']]=s
 return web.json_response(_public(s))

async def clear_result(request):
 data=await request.json();_admin(data)
 async with LOCK:
  s=_pack(_get(request.match_info['lid']));f=_find(s,request.match_info['mid'])
  if f['source']!='legacy':return web.json_response({'error':'Nur importierte Ergebnisse können hier zurückgesetzt werden'},status=409)
  f.update(source='open',legs=None,sets=None,game=None,undo=None,entered_at=None,import_note='');f['version']+=1
  try:await asyncio.to_thread(_persist_sync,s)
  except Exception as e:return web.json_response({'error':str(e)},status=503)
  LEAGUES[s['id']]=s
 return web.json_response(_public(s))

async def game_state(request):
 s=_get(request.match_info['lid']);return web.json_response(_match_state(s,_find(s,request.match_info['mid'])))
async def game_start(request):
 data=await request.json()
 async with LOCK:
  s=_pack(_get(request.match_info['lid']));f=_find(s,request.match_info['mid'])
  if f['source']=='legacy':return web.json_response({'error':'Historisches Match bereits abgeschlossen'},status=409)
  if f['starter'] is None:
   starter=data.get('starter')
   if starter not in (0,1):return web.json_response({'error':'Anwurf auswählen'},status=400)
   f['starter']=starter;m=_unpack_match(f['game']) if f['game'] else None
   if m is None:
    names={p['id']:p['name'] for g in s['groups'] for p in g['players']}
    m=Match(Rules(start_score=s['start_score'],mode='legs',max_legs=f['best_of'],best_of_sets=f['best_of'],best_of_legs_per_set=5,allow_draw=f['best_of']%2==0),(names[f['a']],names[f['b']]))
   m.current=starter;m.first_throw=starter;f['game']=_pack_match(m);f['started_at']=_now();f['version']+=1
   try:await asyncio.to_thread(_persist_sync,s)
   except Exception as e:return web.json_response({'error':str(e)},status=503)
   LEAGUES[s['id']]=s
 return web.json_response(_match_state(s,f))
async def game_throw(request):
 data=await request.json()
 async with LOCK:
  s=_pack(_get(request.match_info['lid']));f=_find(s,request.match_info['mid'])
  if f['source']=='legacy' or f['starter'] is None:return web.json_response({'error':'Match abgeschlossen oder Anwurf nicht gewählt'},status=409)
  if data.get('version')!=f['version']:return web.json_response({'error':'Spielstand wurde auf anderem Gerät geändert – bitte aktualisieren'},status=409)
  g=_unpack_match(f['game'])
  if g.done:return web.json_response({'error':'Spiel beendet'},status=409)
  f['undo']=_pack_match(g)
  try:g.submit(g.current,int(data['points']),darts=int(data.get('darts',3)),checkout=bool(data.get('checkout',False)),checkout_attempts=int(data.get('checkout_attempts',0)),bullfinish=bool(data.get('bullfinish',False)))
  except (KeyError,TypeError,ValueError) as e:return web.json_response({'error':str(e)},status=400)
  f['game']=_pack_match(g);f['version']+=1
  if g.done:f.update(source='scorer',legs=g.legs[:],sets=g.sets[:],entered_at=_now(),finished_at=_now())
  try:await asyncio.to_thread(_persist_sync,s)
  except Exception as e:return web.json_response({'error':f'Google Sheets: Aufnahme nicht gespeichert – {e}'},status=503)
  LEAGUES[s['id']]=s
 return web.json_response(_match_state(s,f))
async def game_undo(request):
 async with LOCK:
  s=_pack(_get(request.match_info['lid']));f=_find(s,request.match_info['mid'])
  if not f['undo']:return web.json_response({'error':'Keine Aufnahme zurückzunehmen'},status=409)
  f['game']=f['undo'];f['undo']=None;f['version']+=1;f.update(source='open',legs=None,sets=None,finished_at=None,entered_at=None)
  try:await asyncio.to_thread(_persist_sync,s)
  except Exception as e:return web.json_response({'error':str(e)},status=503)
  LEAGUES[s['id']]=s
 return web.json_response(_match_state(s,f))

def register_stingray_league(app,auth):
 def protected(fn):
  async def wrapper(request):auth(request);return await fn(request)
  return wrapper
 app.router.add_get('/dart/api/league',protected(listing))
 app.router.add_post('/dart/api/league',protected(create))
 app.router.add_get('/dart/api/league/{lid}',protected(detail))
 app.router.add_post('/dart/api/league/{lid}/matches/{mid}/result',protected(manual_result))
 app.router.add_post('/dart/api/league/{lid}/matches/{mid}/clear',protected(clear_result))
 app.router.add_get('/dart/api/league/{lid}/matches/{mid}',protected(game_state))
 app.router.add_post('/dart/api/league/{lid}/matches/{mid}/start',protected(game_start))
 app.router.add_post('/dart/api/league/{lid}/matches/{mid}/throw',protected(game_throw))
 app.router.add_post('/dart/api/league/{lid}/matches/{mid}/undo',protected(game_undo))
