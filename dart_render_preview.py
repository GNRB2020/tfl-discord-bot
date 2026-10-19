"""Password-protected Phase-2 preview routes for the existing aiohttp app.

NOT suitable for production matches: one process-local test match, no persistent storage.
"""
import hmac
import os
from aiohttp import web
import dart_preview
from dart_engine import Match, Rules


def register_dart_render_preview(app: web.Application) -> None:
    password = os.environ.get('DART_TEST_PASSWORD', '')
    if len(password) < 12:
        print('[DART] Preview disabled: configure DART_TEST_PASSWORD (12+ characters) on Render')
        return

    # One sandbox match, intentionally disconnected from competitions.
    dart_preview.MATCH = Match(Rules(max_legs=6, allow_draw=True), ('Spieler A', 'Spieler B'))

    def require_auth(handler):
        async def protected(request: web.Request):
            auth = request.headers.get('Authorization', '')
            try:
                import base64
                if not auth.startswith('Basic '):
                    raise ValueError('missing basic auth')
                plain = base64.b64decode(auth[6:], validate=True).decode('utf-8')
                user, secret = plain.split(':', 1)
            except (ValueError, UnicodeDecodeError):
                user, secret = '', ''
            if not (hmac.compare_digest(user, 'darttest') and
                    hmac.compare_digest(secret, password)):
                return web.Response(status=401, text='Authentication required', headers={
                    'WWW-Authenticate': 'Basic realm="Stingrays Dart Test"',
                    'Cache-Control': 'no-store',
                })
            response = await handler(request)
            response.headers['Cache-Control'] = 'no-store'
            return response
        return protected

    app.router.add_get('/dart/', require_auth(dart_preview.page))
    app.router.add_get('/dart/api/state', require_auth(dart_preview.status))
    app.router.add_post('/dart/api/new', require_auth(dart_preview.reset))
    app.router.add_post('/dart/api/throw', require_auth(dart_preview.throw))
    print('[DART] Protected Phase-2 preview available at /dart/')
