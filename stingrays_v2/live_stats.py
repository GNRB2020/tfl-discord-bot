"""Small, side-effect free live match-statistic helpers.

The active board feed and match report must treat busts consistently:
a bust consumes darts but awards zero points.
"""
from __future__ import annotations


def live_averages(visits):
    """Return a two-player three-dart average, None for no throws.

    This function only processes the already persisted match visits; it never
    estimates averages from manually entered scores.
    """
    totals = [[0, 0], [0, 0]]  # awarded points, thrown darts
    for visit in visits or []:
        if not isinstance(visit, dict):
            continue
        player = visit.get('player')
        if type(player) is not int or player not in (0, 1):
            continue
        try:
            score = int(visit.get('score', 0) or 0)
            darts = int(visit.get('darts', 3))
        except (TypeError, ValueError, OverflowError):
            continue
        if not 1 <= darts <= 3 or not 0 <= score <= 180:
            continue
        totals[player][0] += 0 if visit.get('bust') else score
        totals[player][1] += darts
    return [round(3 * points / darts, 2) if darts else None
            for points, darts in totals]
