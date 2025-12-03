import datetime

# Fake-Timezone-Konstante, weil Frontend sie importiert
BERLIN_TZ = datetime.timezone(datetime.timedelta(hours=1))

# Damit api.py importieren kann
def sheets_required():
    return True

# Dummy Funktionen, die NICHT auf Google Sheets zugreifen
async def fetch_upcoming_events():
    return []

async def fetch_results():
    return []
