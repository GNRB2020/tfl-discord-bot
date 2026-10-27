"""Consistent handling of post-match advancement failures.

A match is committed before advancement begins. The client must distinguish
"score saved" from "bracket advanced"; never return false success.
"""
import logging
from uuid import uuid4
from aiohttp import web

log=logging.getLogger(__name__)


async def advance_with_feedback(req, competition_id):
    from .tournament_automation import progress
    try:
        await progress(req,competition_id)
    except web.HTTPConflict as exc:
        # A genuine qualification tie is a normal administrative decision,
        # not a failed score write or a reason to retry scoring.
        return {'status':'attention','message':exc.text or 'Folgerunde benötigt eine Adminentscheidung.'}
    except Exception:
        incident=uuid4().hex[:10]
        log.exception('Stingray advancement failed; incident=%s competition=%s',incident,competition_id)
        return {'status':'error','message':'Ergebnis gespeichert, automatische Folgerunde fehlgeschlagen. Bitte in der Verwaltung erneut prüfen.','incident':incident}
    return {'status':'ok'}
