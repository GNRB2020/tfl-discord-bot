"""Deterministic in-memory tournament dry-run for administrators.

K.O. rounds use the very same planning function as the live progression.
No production data is read or changed.
"""
from __future__ import annotations
from collections import Counter
from random import Random
from .rules import bracket_pairs, rank_rows, round_robin

MAX_PLAYERS = 128


def _integer(value, name, minimum, maximum):
    try:
        number = int(value)
    except (ValueError, TypeError):
        raise ValueError(f'{name}: ganze Zahl erforderlich') from None
    if number < minimum or number > maximum:
        raise ValueError(f'{name}: {minimum} bis {maximum} erlaubt')
    return number


def _score(rng, best_of):
    needed = best_of // 2 + 1
    loser = rng.randrange(needed)
    return (needed, loser) if rng.getrandbits(1) else (loser, needed)


def _match(rng, a, b, best_of, phase, round_no):
    x, y = _score(rng, best_of)
    return {'player1_id': a, 'player2_id': b, 'status': 'finished',
            'legs1': x, 'legs2': y, 'winner': a if x > y else b,
            'phase': phase, 'round': round_no}


def _knockout(rng, players, best_of, kind='single_ko', origin=None):
    """Play exactly the same round-by-round plan as the production engine."""
    from .ko_progression import plan_next_ko_round
    if kind not in ('single_ko', 'double_ko'):
        raise ValueError('Unbekannte K.-o.-Art')
    if len(players) < 2 or len(set(players)) != len(players):
        raise ValueError('K.-o.-Startliste muss mindestens zwei unterschiedliche Spieler enthalten')
    roster = list(players)
    first = bracket_pairs(roster)
    initial_byes = [p for a,b in first for p in (a,b) if p is not None and (a is None or b is None)]
    pairs = [(a,b) for a,b in first if a is not None and b is not None]
    games = []
    byes = len(initial_byes)
    rematches = 0
    reset_final = False
    round_no = 1
    while True:
        if round_no > 32:
            raise RuntimeError('K.-o.-Simulation konnte nicht beendet werden')
        for pos,(a,b) in enumerate(pairs,1):
            if origin and round_no == 1 and origin.get(a) == origin.get(b):
                rematches += 1
            match = _match(rng, a, b, best_of, kind, round_no)
            match['round_number'] = round_no
            match['bracket_position'] = pos
            match['sets1'] = None
            match['sets2'] = None
            games.append(match)
        plan = plan_next_ko_round(kind,roster,games,initial_byes)
        if plan['completed']:
            champion=plan['champion']
            break
        byes += len(plan['byes'])
        reset_final = reset_final or plan['reset_final']
        pairs = plan['pairs']
        round_no = plan['round']
    losses=Counter({p:0 for p in roster})
    for m in games:
        loser=m['player2_id'] if m['winner']==m['player1_id'] else m['player1_id']
        losses[loser]+=1
    if kind == 'single_ko' and len(games) != len(roster)-1:
        raise RuntimeError('Single-K.O. hat eine unvollständige Begegnungszahl')
    if kind == 'double_ko' and any(losses[p] != 2 for p in roster if p != champion):
        raise RuntimeError('Doppel-K.O.: Spieler mit weniger als zwei Niederlagen ausgeschieden')
    return {'format':kind,'participants':len(roster),'matches':len(games),
            'rounds':round_no,'byes':byes,'champion':champion,
            'same_group_first_round':rematches,'reset_final':reset_final,'games':games}


def simulate(spec):
    """Validate and execute a complete tournament in-memory; no database I/O."""
    count = _integer(spec.get('players', 64), 'Spieler', 2, MAX_PLAYERS)
    fmt = str(spec.get('format', 'groups'))
    if fmt not in ('groups', 'league', 'single_ko', 'double_ko'):
        raise ValueError('Unbekanntes Vorrundenformat')
    group_count = _integer(spec.get('groups', 8), 'Gruppen', 1, 32) if fmt == 'groups' else 1
    if fmt == 'groups' and (group_count < 2 or count < 2 * group_count):
        raise ValueError('Mindestens zwei Spieler je Gruppe erforderlich')
    qualifiers = _integer(spec.get('qualifiers', 2), 'Direktqualifizierte', 1, MAX_PLAYERS)
    wildcards = _integer(spec.get('wildcards', 0), 'Zusätzliche Qualifikanten', 0, MAX_PLAYERS)
    best_of = _integer(spec.get('best_of', 5), 'Best of', 1, 101)
    if best_of % 2 == 0:
        raise ValueError('Für diese Simulation muss Best of ungerade sein')
    seed = _integer(spec.get('seed', 42), 'Seed', 0, 2_147_483_647)
    follow = str(spec.get('follow_format', 'single_ko'))
    if follow not in ('single_ko', 'double_ko'):
        raise ValueError('Die Simulation der Folgerunde unterstützt Single- oder Doppel-K.O.')
    rng = Random(seed)
    people = [f'Spieler {i:03}' for i in range(1, count + 1)]
    rng.shuffle(people)
    if fmt in ('single_ko', 'double_ko'):
        ko = _knockout(rng, people, best_of, kind=fmt)
        return {'simulation': True, 'writes': 0, 'seed': seed, 'players': count,
                'preliminary': {'format': fmt, 'groups': 0, 'matches': 0, 'fixtures': []},
                'qualification': {'direct': count, 'additional': 0, 'cutoff_tie': False},
                'final': {k: v for k, v in ko.items() if k != 'games'},
                'total_matches': ko['matches'],
                'checks': ['Jeder Spieler genau einmal ausgelost', 'Kein echtes Ergebnis verändert',
                           'Jeder ausgeschiedene Spieler besitzt die nötige Anzahl Niederlagen']}
    buckets = [[] for _ in range(group_count)]
    for ix, name in enumerate(people):
        buckets[ix % group_count].append(name)
    if any(len(b) < 2 for b in buckets):
        raise RuntimeError('Gruppe mit weniger als zwei Spielern')
    if qualifiers > min(map(len, buckets)):
        raise ValueError('Direktqualifizierte je Gruppe überschreiten die kleinste Gruppengröße')
    direct, candidates, all_games, origin = [], [], [], {}
    standings = []
    for gi, bucket in enumerate(buckets):
        origin.update({p: gi for p in bucket})
        group_games = []
        for rnd, a, b in round_robin(bucket):
            group_games.append(_match(rng, a, b, best_of, 'Gruppe ' + str(gi + 1), rnd))
        all_games.extend(group_games)
        ranking = rank_rows(group_games, bucket)
        direct.extend(row['player_id'] for row in ranking[:qualifiers])
        standings.append({'group': gi + 1, 'players': len(bucket), 'matches': len(group_games),
                          'leader': ranking[0]['player_id']})
        for place, row in enumerate(ranking[qualifiers:], start=qualifiers + 1):
            played = max(1, row['played'])
            metric = (-(place), row['points'] / played,
                      (row['legs_for'] - row['legs_against']) / played, row['legs_for'] / played)
            candidates.append((metric, row['player_id']))
    candidates.sort(key=lambda item: item[0], reverse=True)
    if wildcards > len(candidates):
        raise ValueError('Nicht genügend Spieler für zusätzliche Qualifikationsplätze')
    boundary = wildcards and wildcards < len(candidates) and candidates[wildcards - 1][0] == candidates[wildcards][0]
    # Tied qualifiers in a simulation are selected reproducibly for inspection.
    # Real competitions still require an explicit administrator decision.
    qualified = direct + [name for _, name in candidates[:wildcards]]
    if len(set(qualified)) != len(qualified):
        raise RuntimeError('Ein Spieler wurde doppelt qualifiziert')
    if len(qualified) < 2:
        raise ValueError('Mindestens zwei qualifizierte Spieler für das Finale erforderlich')
    # Use the same initial bracket spreading as the production progression.
    # In a real event, group clashes can still be unavoidable (e.g. too few groups).
    if follow == 'single_ko':
        from .tournament_automation import spread_groups_in_bracket
        qualified = spread_groups_in_bracket(qualified, {str(k): str(v) for k, v in origin.items()})
    ko = _knockout(rng, qualified, best_of, kind=follow, origin=origin)
    expected_groups = sum(len(b) * (len(b) - 1) // 2 for b in buckets)
    if len(all_games) != expected_groups:
        raise RuntimeError('Gruppenspielplan unvollständig')
    return {'simulation': True, 'writes': 0, 'seed': seed, 'players': count,
            'preliminary': {'format': fmt, 'groups': group_count,
                            'matches': expected_groups, 'standings': standings},
            'qualification': {'direct': len(direct), 'additional': wildcards,
                              'cutoff_tie': bool(boundary),
                              'note': 'Realer Wettbewerb benötigt Adminentscheidung an der Grenze' if boundary else 'Eindeutige Auswahl'},
            'final': {k: v for k, v in ko.items() if k != 'games'},
            'total_matches': len(all_games) + ko['matches'],
            'checks': ['Gruppenplan vollständig', 'Keine doppelte Qualifikation',
                       'Finale abgeschlossen', 'Simulation ohne Datenbankänderung']}
