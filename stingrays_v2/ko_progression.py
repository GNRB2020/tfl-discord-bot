"""Shared, deterministic K.O. progression for real matches and dry-run tests.

No database access: one phase's finished games and starting roster go in;
next round, a bye schedule or the champion comes out. The caller owns the
transaction, authorization and persistence. Two-loss elimination ALWAYS keeps
one-loss participants alive; a reset final is scheduled when necessary.
"""
from collections import Counter
from .rules import bracket_pairs


class BracketStateError(ValueError):
    """The persisted knockout bracket violates a sporting invariant."""


def match_winner(match):
    s1, s2 = match.get('sets1'), match.get('sets2')
    if s1 is None or s2 is None or (s1 == 0 and s2 == 0):
        s1, s2 = match.get('legs1'), match.get('legs2')
    if s1 is None or s2 is None or s1 == s2:
        return None
    return match['player1_id'] if s1 > s2 else match['player2_id']


def _pairs_avoiding_rematches(players, history):
    """Pair each loss bracket tightly; one odd entrant can get a bye."""
    available = list(players)
    pairs = []
    while len(available) > 1:
        p = available.pop(0)
        # The oldest/lowest-seeded remaining player is preferred on ties.
        opponent = min(available, key=lambda q: (history[frozenset((p, q))], available.index(q)))
        available.remove(opponent)
        pairs.append((p, opponent))
    return pairs, available


def plan_next_ko_round(format_name, participants, matches, bye_players=()):
    """Plan one round after the last completed round.

    Input games must be finished, carry round_number, player IDs and scores.
    Returns {'completed', 'champion', 'pairs', 'byes', 'round', 'reset_final'}.
    Empty 'pairs' is *never* returned for an active phase.
    """
    if format_name not in ('single_ko', 'double_ko'):
        raise BracketStateError('Unbekanntes K.-o.-Format')
    roster = list(participants)
    if len(roster) < 2 or len(set(roster)) != len(roster):
        raise BracketStateError('K.-o.-Teilnehmerliste ist unvollständig oder doppelt')
    if not matches:
        raise BracketStateError('Die erste K.-o.-Runde wurde noch nicht ausgelost')
    allowed = set(roster)
    byes = list(bye_players)
    if len(byes) != len(set(byes)) or any(p not in allowed for p in byes):
        raise BracketStateError('Ungültige Freiloszuordnung')
    ordered = sorted(matches, key=lambda m: (int(m.get('round_number') or 1), int(m.get('bracket_position') or 0)))
    losses = Counter({p: 0 for p in roster})
    history = Counter()
    round_entrants = {}
    round_winners = {}
    for m in ordered:
        rnd = int(m.get('round_number') or 1)
        if rnd < 1 or m.get('status') != 'finished':
            raise BracketStateError('Eine K.-o.-Begegnung ist noch offen oder hat eine ungültige Runde')
        a, b = m['player1_id'], m['player2_id']
        if a not in allowed or b not in allowed or a == b:
            raise BracketStateError('Ungültige oder doppelt eingetragene K.-o.-Teilnehmer')
        present = round_entrants.setdefault(rnd, set())
        if a in present or b in present:
            raise BracketStateError('Ein Spieler ist zweimal in derselben Runde angesetzt')
        present.update((a, b))
        if losses[a] >= (1 if format_name == 'single_ko' else 2) or losses[b] >= (1 if format_name == 'single_ko' else 2):
            raise BracketStateError('Bereits ausgeschiedener Spieler wurde erneut angesetzt')
        w = match_winner(m)
        if w is None:
            raise BracketStateError('K.-o.-Ergebnis ohne eindeutigen Sieger')
        loser = b if w == a else a
        losses[loser] += 1
        round_winners.setdefault(rnd, []).append(w)
        history[frozenset((a, b))] += 1
    rounds = sorted(round_entrants)
    if rounds != list(range(1, rounds[-1] + 1)):
        raise BracketStateError('Eine K.-o.-Runde fehlt im Turnierverlauf')
    latest = rounds[-1]
    if format_name == 'single_ko':
        # No player may vanish between rounds (and no omitted survivor may be
        # silently treated as eliminated). This also catches manual edits to a
        # later round that bypass the initial editable bracket.
        for rnd in rounds[1:]:
            expected=set(round_winners[rnd-1])
            if rnd==2:expected.update(byes)
            if round_entrants[rnd] != expected:
                raise BracketStateError('Fehlende oder fremde Teilnehmer in der K.-o.-Folgerunde')
        if latest == 1:
            # First-round matches retain their original bracket positions, even
            # when the organizer has swapped the draw before release.
            if set(byes) & round_entrants[1] or len(byes) + len(round_entrants[1]) != len(roster):
                raise BracketStateError('Erste K.-o.-Runde hat fehlende oder doppelte Spieler')
            slots_count = (1 << (len(roster) - 1).bit_length()) // 2
            if len(round_winners[1]) + len(byes) != slots_count:
                raise BracketStateError('Freilosanzahl passt nicht zum K.-o.-Baum')
            slots = [None] * slots_count
            for m in ordered:
                if int(m.get('round_number') or 1) != 1:continue
                pos=int(m.get('bracket_position') or 0)
                if pos < 1 or pos > slots_count or slots[pos-1] is not None:
                    raise BracketStateError('Ungültige Position im K.-o.-Baum')
                slots[pos-1]=match_winner(m)
            free=(i for i,v in enumerate(slots) if v is None)
            for player in byes:slots[next(free)]=player
            remaining=slots
        else:
            latest_games = [m for m in ordered if int(m.get('round_number') or 1) == latest]
            if [int(m.get('bracket_position') or 0) for m in latest_games] != list(range(1,len(latest_games)+1)):
                raise BracketStateError('Unvollständige Positionen der K.-o.-Runde')
            remaining=[match_winner(m) for m in latest_games]
        if len(remaining)!=len(set(remaining)):
            raise BracketStateError('Siegerliste enthält einen Spieler mehrfach')
        if len(remaining) == 1:
            return {'completed': True, 'champion': remaining[0], 'pairs': [], 'byes': [], 'round': latest, 'reset_final': False}
        if len(remaining)%2:
            raise BracketStateError('Unvollständige K.-o.-Runde: ungerade Siegerzahl')
        pairs=[(remaining[i],remaining[i+1]) for i in range(0,len(remaining),2)]
        return {'completed': False, 'champion': None, 'pairs': pairs, 'byes': [], 'round': latest + 1, 'reset_final': False}
    # Double elimination: everyone with zero or one loss stays alive.
    active = [p for p in roster if losses[p] < 2]
    if len(active) == 1:
        return {'completed': True, 'champion': active[0], 'pairs': [], 'byes': [], 'round': latest, 'reset_final': False}
    zero = [p for p in active if losses[p] == 0]
    one = [p for p in active if losses[p] == 1]
    if len(active) == 2 and len(zero) == 1 and len(one) == 1:
        # Grand final. If the one-loss challenger wins, both have one loss
        # and the following invocation automatically creates the reset final.
        pairs, future_byes = [(zero[0], one[0])], []
    elif len(active) == 2 and not zero:
        pairs, future_byes = [(one[0], one[1])], []
    else:
        upper, upper_byes = _pairs_avoiding_rematches(zero, history)
        lower, lower_byes = _pairs_avoiding_rematches(one, history)
        pairs, future_byes = upper + lower, upper_byes + lower_byes
    if not pairs:
        raise BracketStateError('Die Doppel-K.-o.-Runde hat keinen möglichen Spielansatz')
    if len({p for pair in pairs for p in pair}) != 2 * len(pairs):
        raise BracketStateError('Doppelte Teilnehmer in der nächsten Runde')
    reset_final = len(active) == 2 and not zero and history[frozenset(active)] > 0
    return {'completed': False, 'champion': None, 'pairs': pairs, 'byes': future_byes, 'round': latest + 1,
            'reset_final': reset_final}
