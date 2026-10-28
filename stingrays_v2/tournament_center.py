"""Read-only operations view for up to 22 boards. No hidden state changes."""
from .api import actor, pool, response, SCHEMA


async def overview(req):
    a = await actor(req)
    if a['role'] not in ('admin', 'tournament'):
        from aiohttp import web
        raise web.HTTPForbidden(text='Nur Turnierleitung und Administratoren')
    async with pool(req).acquire() as db:
        boards = await db.fetch(f'''SELECT b.id,b.label,b.enabled,
            m.id AS match_id,c.id AS competition_id,c.title AS competition,
            p1.display_name AS player1,p2.display_name AS player2,
            m.started_at FROM {SCHEMA}.boards b
            LEFT JOIN {SCHEMA}.matches m ON m.board_id=b.id AND m.status='running'
            LEFT JOIN {SCHEMA}.competitions c ON c.id=m.competition_id AND c.deleted_at IS NULL
            LEFT JOIN {SCHEMA}.players p1 ON p1.id=m.player1_id
            LEFT JOIN {SCHEMA}.players p2 ON p2.id=m.player2_id
            ORDER BY b.id LIMIT 22''')
        unassigned = await db.fetch(f'''SELECT m.id AS match_id,m.competition_id,c.title AS competition,
            p1.display_name AS player1,p2.display_name AS player2,m.started_at
            FROM {SCHEMA}.matches m
            JOIN {SCHEMA}.competitions c ON c.id=m.competition_id AND c.deleted_at IS NULL
            JOIN {SCHEMA}.players p1 ON p1.id=m.player1_id
            JOIN {SCHEMA}.players p2 ON p2.id=m.player2_id
            WHERE m.status='running' AND m.board_id IS NULL
            ORDER BY m.started_at DESC LIMIT 30''')
        ready = await db.fetch(f'''SELECT m.id AS match_id,m.competition_id,c.title AS competition,
            p1.display_name AS player1,p2.display_name AS player2,
            ph.name AS phase, m.round_number
            FROM {SCHEMA}.matches m
            JOIN {SCHEMA}.competitions c ON c.id=m.competition_id AND c.deleted_at IS NULL
            LEFT JOIN {SCHEMA}.phases ph ON ph.id=m.phase_id
            JOIN {SCHEMA}.players p1 ON p1.id=m.player1_id
            JOIN {SCHEMA}.players p2 ON p2.id=m.player2_id
            WHERE m.status='open' AND c.status IN ('active','draft')
              AND (ph.id IS NULL OR ph.kind<>'knockout'
                   OR ph.rules->>'bracket_released' IS DISTINCT FROM 'false')
            ORDER BY c.title,ph.phase_order,m.round_number,m.bracket_position,m.id
            LIMIT 60''')
        counts = await db.fetchrow(f'''SELECT
            (SELECT COUNT(*) FROM {SCHEMA}.matches m JOIN {SCHEMA}.competitions c
             ON c.id=m.competition_id AND c.deleted_at IS NULL WHERE m.status='running') AS running,
            (SELECT COUNT(*) FROM {SCHEMA}.matches m JOIN {SCHEMA}.competitions c
             ON c.id=m.competition_id AND c.deleted_at IS NULL WHERE m.status='open') AS open_total,
            (SELECT COUNT(*) FROM {SCHEMA}.competitions
             WHERE deleted_at IS NULL AND status='active') AS active_competitions''')
    present = [dict(x) for x in boards]
    return response({'boards': present, 'unassigned': list(map(dict, unassigned)),
                     'ready': list(map(dict, ready)), 'counts': dict(counts),
                     'board_count': len(present),
                     'free_boards': sum(bool(x['enabled'] and x['match_id'] is None) for x in present),
                     'note': 'Startbereite Begegnungen: maximal 60 angezeigt. Weitere über Wettbewerbe öffnen.'})


async def simulation(req):
    from .api import body
    from .tournament_simulator import simulate
    from aiohttp import web
    await actor(req, 'admin')
    spec = await body(req)
    try:
        data = simulate(spec)
    except (ValueError, RuntimeError) as exc:
        raise web.HTTPBadRequest(text=str(exc)) from exc
    return response(data)
