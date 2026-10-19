"""Google Sheets persistence for shared training tournaments. No credentials in source."""
import asyncio
import base64
import zlib
import json
import os
from datetime import datetime, timezone
from threading import Lock
from sheets_connection import get_spreadsheet

SPREADSHEET_ID = os.getenv('DART_SPREADSHEET_ID', '1DNlOzaOXzCDkZjoK_KU_ixhuQlwWPkcp4hVMQWNiHvs')
TAB = 'DART_TournamentSnapshots'
_sheet_lock = Lock()


def _sheet():
    ss = get_spreadsheet(SPREADSHEET_ID)
    try:
        return ss.worksheet(TAB)
    except Exception as exc:
        import gspread
        if not isinstance(exc, gspread.WorksheetNotFound):
            raise
        return ss.add_worksheet(title=TAB, rows=500, cols=4)


def _save_sync(tournament_id, data):
    raw=json.dumps(data, ensure_ascii=False, separators=(',',':')).encode('utf-8')
    payload=base64.b64encode(zlib.compress(raw,level=9)).decode('ascii')
    if len(payload)>45000:
        raise ValueError('Turnier-Snapshot zu groß für eine Google-Sheets-Zelle')
    with _sheet_lock:
        ws=_sheet()
        values=ws.get_all_values()
        if not values:
            ws.update(range_name='A1:D1', values=[['tournament_id','updated_utc','json_snapshot','schema']])
            values=[['tournament_id','updated_utc','json_snapshot','schema']]
        now=datetime.now(timezone.utc).isoformat()
        row=next((idx+1 for idx, v in enumerate(values) if v and v[0]==tournament_id),None)
        cells=[[tournament_id,now,payload,'2']]
        if row: ws.update(range_name=f'A{row}:D{row}',values=cells)
        else: ws.append_row(cells[0], value_input_option='RAW')


def _load_sync():
    with _sheet_lock:
        rows=_sheet().get_all_values()
    out={}
    for row in rows[1:]:
        if len(row)<3 or not row[0]: continue
        try:
            if len(row)>3 and row[3]=='2':
                out[row[0]]=json.loads(zlib.decompress(base64.b64decode(row[2])).decode('utf-8'))
            else:
                out[row[0]]=json.loads(row[2])
        except (ValueError,TypeError,zlib.error):continue
    return out


async def save(tournament_id,data):
    await asyncio.to_thread(_save_sync,tournament_id,data)

async def load_all():
    return await asyncio.to_thread(_load_sync)
