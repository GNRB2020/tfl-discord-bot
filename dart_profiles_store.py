"""Google Sheets profile directory and completed-game archive. No credentials in source.

Profiles are edited in DART_Profiles: profile_id | display_name | active.
Never edit profile_id for existing users. The game archive contains detail for reaggregation.
"""
from __future__ import annotations
import asyncio, base64, json, os, threading, zlib
from datetime import datetime, timezone
from pathlib import Path
from sheets_connection import get_spreadsheet

SHEET_ID = os.getenv('DART_SPREADSHEET_ID', '1DNlOzaOXzCDkZjoK_KU_ixhuQlwWPkcp4hVMQWNiHvs')
LOCK = threading.RLock()
HEADER_PROFILES = ['profile_id','display_name','active']
HEADER_GAMES = ['game_id','timestamp_utc','kind','payload_b64z']


def _ws(title, header):
    import gspread
    book = get_spreadsheet(SHEET_ID)
    try: ws=book.worksheet(title)
    except gspread.WorksheetNotFound:
        ws=book.add_worksheet(title=title,rows=1000,cols=len(header))
    first=ws.row_values(1)
    if not first:ws.update(range_name=f'A1:{chr(64+len(header))}1',values=[header])
    elif first!=header:raise RuntimeError(f'{title}: Falsche Spaltenüberschriften: {first}')
    return ws


def _seed_profiles(ws):
    if len(ws.col_values(1))>1:return
    source=Path(__file__).resolve().parent/'dart_ui'/'profiles.json'
    initial=json.loads(source.read_text(encoding='utf-8'))
    rows=[[f'STR-{int(p["id"]):04d}',p['display_name'],'1'] for p in initial]
    if rows:ws.update(range_name=f'A2:C{len(rows)+1}',values=rows,value_input_option='RAW')


def _profiles_sync():
    with LOCK:
        ws=_ws('DART_Profiles',HEADER_PROFILES)
        _seed_profiles(ws)
        rows=ws.get_all_values()[1:]
        # New member: enter the name in column B, leave ID in A blank.
        # Assign an immutable ID automatically, so sheet edits do not break stats.
        used={r[0].strip() for r in rows if r and r[0].strip()}
        n=max([int(x[4:]) for x in used if x.startswith('STR-') and x[4:].isdigit()] or [0])
        for rowno,row in enumerate(rows,2):
            if len(row)>=2 and row[1].strip() and not row[0].strip():
                n+=1
                while f'STR-{n:04d}' in used:n+=1
                pid=f'STR-{n:04d}';ws.update_cell(rowno,1,pid);used.add(pid);row[0]=pid
    result=[]; seen=set()
    for row in rows:
        if len(row)<2:continue
        pid,name=row[0].strip(),row[1].strip()
        if not pid or not name:continue
        if pid in seen:raise RuntimeError(f'Doppelte Profil-ID im Sheet: {pid}')
        seen.add(pid)
        if len(row)>2 and row[2].strip().lower() in ('0','false','nein','inaktiv'):continue
        result.append({'id':pid,'display_name':name})
    return result

async def profiles():return await asyncio.to_thread(_profiles_sync)


def _save_sync(game_id,kind,payload):
    packed=base64.b64encode(zlib.compress(json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode(),9)).decode('ascii')
    if len(packed)>45000:raise ValueError('Spielhistorie für Google-Sheets-Zelle zu groß')
    with LOCK:
        ws=_ws('DART_ProfileGames',HEADER_GAMES)
        ids=ws.col_values(1)
        row=ids.index(game_id)+1 if game_id in ids else len(ids)+1
        ws.update(range_name=f'A{row}:D{row}',values=[[game_id,datetime.now(timezone.utc).isoformat(),kind,packed]],value_input_option='RAW')

async def save_game(game_id,kind,payload):await asyncio.to_thread(_save_sync,game_id,kind,payload)


def _load_games_sync():
    with LOCK:rows=_ws('DART_ProfileGames',HEADER_GAMES).get_all_values()[1:]
    games=[]
    for index,row in enumerate(rows,2):
        if len(row)<4 or not row[0]:continue
        try:
            obj=json.loads(zlib.decompress(base64.b64decode(row[3])).decode())
            games.append({'id':row[0],'timestamp':row[1],'kind':row[2],'data':obj})
        except Exception as exc:
            raise RuntimeError(f'Ungültige Spielhistorie in Zeile {index}: {exc}') from exc
    return games

async def games():return await asyncio.to_thread(_load_games_sync)


def _match_stats(g, idx):
    vs=[v for v in g.visits if v.player==idx]
    s=g.summary()['players'][idx]
    first_points=first_darts=0
    for leg in {v.leg_index for v in vs}:
        used=0
        for v in [x for x in vs if x.leg_index==leg]:
            if used+v.darts>9:break
            first_points+=0 if v.bust else v.score
            first_darts+=v.darts;used+=v.darts
    return {'darts':sum(v.darts for v in vs),'points':sum(0 if v.bust else v.score for v in vs),
        'first_points':first_points,'first_darts':first_darts,'legs':g.legs[idx],
        'visits95':sum(v.score>=95 and not v.bust for v in vs),
        'visits133':sum(v.score>=133 and not v.bust for v in vs),
        'visits171':sum(v.score>=171 and not v.bust for v in vs),
        'scores180':sum(v.score==180 and not v.bust for v in vs),
        'bf':s['bullfinish_details'],'hf':s['highfinish_details'],'ld':s['lowdart_details'],
        'highscores':s['highscore_details'],'checkouts':sum(int(v.checkout) for v in vs)}


def aggregate_profile(profile, archived, tournaments):
    # Historical records without profile IDs can match by exact display name; IDs take precedence.
    pid=profile['id'];name=profile['display_name']; out={'id':pid,'name':name,'matches':0,'wins':0,'legs':0,
      'darts':0,'points':0,'first_points':0,'first_darts':0,'visits95':0,'visits133':0,'visits171':0,
      'scores180':0,'bf':[],'hf':[],'ld':[],'highscores':[],'checkouts':0,'sau_sessions':0,
      'sau_success':0,'sau_marks':0,'tug_sessions':0,'tug_wins':0,'sources':[]}
    def belongs(ids,names,i):
        chosen=ids[i] if ids and i<len(ids) else None
        return chosen==pid if chosen else names[i]==name
    def add_match(g,ids,source):
        if not g.done:return
        for i in range(2):
            if not belongs(ids,g.names,i):continue
            z=_match_stats(g,i)
            for k,v in z.items():
                if isinstance(v,list):out[k].extend(v)
                else:out[k]+=v
            out['matches']+=1;out['wins']+=int(g.legs[i]>g.legs[1-i] or g.sets[i]>g.sets[1-i])
            out['sources'].append(source)
    from dart_engine import Match, Rules, Visit
    for item in archived:
        d=item['data'];kind=item['kind'];ids=d.get('profile_ids',[])
        if kind=='x01' and d.get('done'):
            raw=d['match'];g=Match(Rules(**raw['rules']),tuple(raw['names']))
            for k in ('remaining','legs','sets','current','first_throw','leg_number','done'):setattr(g,k,raw[k])
            g.visits=[Visit(**v) for v in raw['visits']]
            add_match(g,ids,'X01 Training')
        elif kind=='sau' and d.get('finished') and (ids[:1]==[pid] or (not ids and d.get('name')==name)):
            out['sau_sessions']+=1;out['sau_success']+=sum(d['marks'].get(str(n),0) for n in range(4,13));out['sau_marks']+=d['marks']['sau']
        elif kind=='tug' and d.get('finished'):
            for i in range(2):
                if belongs(ids,d['names'],i):out['tug_sessions']+=1;out['tug_wins']+=d['wins'][i]
    for t in tournaments:
        pids=t.get('profile_ids')
        for m in t['matches']:
            g=m['game']
            if not g or not g.done:continue
            ids=[pids[t['players'].index(n)] if pids and n in t['players'] else None for n in g.names] if pids else []
            add_match(g,ids,'Trainingsturnier: '+t['title'])
    out['average']=round(out['points']*3/out['darts'],2) if out['darts'] else 0
    out['first9']=round(out['first_points']*3/out['first_darts'],2) if out['first_darts'] else 0
    out['specials']=len(out['bf'])+len(out['hf'])+len(out['ld'])+len(out['highscores'])
    return out
