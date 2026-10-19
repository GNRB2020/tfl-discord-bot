"""Pure scoring logic for a two-player darts match. No persistence/network I/O."""
from dataclasses import dataclass, field
from typing import Literal

# Allowed final dart in double-out; 50 represents double bull.
DOUBLES = set(range(2, 41, 2)) | {50}
SINGLES = set(range(1, 21)) | {25, 50}
TRIPLES = {3 * n for n in range(1, 21)}
ONE_DART = DOUBLES
TWO_DART = {a + b for a in (SINGLES | DOUBLES | TRIPLES) for b in DOUBLES}
THREE_DART = {a + b + c for a in (SINGLES | DOUBLES | TRIPLES) for b in (SINGLES | DOUBLES | TRIPLES) for c in DOUBLES}


def possible_checkout_darts(rest: int) -> list[int]:
    return [n for n, values in ((1, ONE_DART), (2, TWO_DART), (3, THREE_DART)) if rest in values]


@dataclass(frozen=True)
class Rules:
    start_score: int = 501
    mode: Literal['legs', 'sets'] = 'legs'
    max_legs: int = 6  # total legs in legs-mode, NOT first-to
    best_of_sets: int = 5
    best_of_legs_per_set: int = 5
    allow_draw: bool = True
    double_out: bool = True

    def __post_init__(self):
        if self.start_score < 2 or self.mode not in ('legs', 'sets'):
            raise ValueError('Invalid start score or mode')
        if self.max_legs < 1 or self.best_of_sets < 1 or self.best_of_legs_per_set < 1:
            raise ValueError('Leg and set counts must be positive')
        if self.mode == 'sets' and (self.best_of_sets % 2 == 0 or self.best_of_legs_per_set % 2 == 0):
            raise ValueError('Best-of sets and legs per set must be odd')
        if self.mode == 'legs' and not self.allow_draw and self.max_legs % 2 == 0:
            raise ValueError('Even max legs requires draw permission or a deciding-leg rule')


@dataclass
class Visit:
    player: int
    score: int
    darts: int
    checkout_attempts: int = 0
    checkout: bool = False
    bullfinish: bool = False
    bust: bool = False
    leg_index: int = 0


@dataclass
class Match:
    rules: Rules
    names: tuple[str, str]
    remaining: list[int] = field(default_factory=list)
    legs: list[int] = field(default_factory=lambda: [0, 0])
    sets: list[int] = field(default_factory=lambda: [0, 0])
    visits: list[Visit] = field(default_factory=list)
    current: int = 0
    first_throw: int = 0
    leg_number: int = 0
    done: bool = False

    def __post_init__(self):
        if len(self.names) != 2:
            raise ValueError('Exactly two players needed')
        self.remaining = [self.rules.start_score, self.rules.start_score]

    def submit(self, player: int, points: int, *, darts: int = 3,
               checkout_attempts: int = 0, checkout: bool = False,
               bullfinish: bool = False) -> Visit:
        if self.done or player != self.current:
            raise ValueError('Match ended or wrong player')
        if not isinstance(points, int) or not 0 <= points <= 180:
            raise ValueError('Score must be 0..180')
        if not isinstance(darts, int) or darts not in (1, 2, 3):
            raise ValueError('Darts must be 1..3')
        if not isinstance(checkout_attempts, int) or not 0 <= checkout_attempts <= darts:
            raise ValueError('Invalid checkout attempt count')
        if bullfinish and not checkout:
            raise ValueError('Bullfinish requires checkout')
        remaining = self.remaining[player]
        if checkout:
            if points != remaining:
                raise ValueError('Checkout must equal remaining score')
            if self.rules.double_out and darts not in possible_checkout_darts(remaining):
                raise ValueError('Checkout impossible with selected dart count')
            if bullfinish and not (remaining == 50 or (darts == 2 and remaining - 50 in (SINGLES | DOUBLES | TRIPLES)) or (darts == 3 and remaining - 50 in TWO_DART)):
                raise ValueError('No bull finish route')
            if checkout_attempts < 1:
                checkout_attempts = 1
        else:
            if darts != 3:
                raise ValueError('Non-checkout visits consume 3 darts')
        left = remaining - points
        bust = left < 0 or (self.rules.double_out and left == 1) or (left == 0 and not checkout)
        if checkout and bust:
            raise ValueError('Invalid checkout')
        visit = Visit(player, points, darts, checkout_attempts, checkout, bullfinish, bust, self.leg_number)
        self.visits.append(visit)
        if checkout:
            self.legs[player] += 1
            self.leg_number += 1
            self._finish_leg(player)
        else:
            if not bust:
                self.remaining[player] = left
            self.current = 1 - player
        return visit

    def _finish_leg(self, winner: int):
        r = self.rules
        if r.mode == 'legs':
            played = sum(self.legs)
            lead_unreachable = max(self.legs) > r.max_legs - played + min(self.legs)
            self.done = played >= r.max_legs or lead_unreachable
        else:
            target = r.best_of_legs_per_set // 2 + 1
            if self.legs[winner] >= target:
                self.sets[winner] += 1
                self.legs = [0, 0]
                self.done = self.sets[winner] >= r.best_of_sets // 2 + 1
        if not self.done:
            self.remaining = [r.start_score, r.start_score]
            self.first_throw = 1 - self.first_throw
            self.current = self.first_throw

    def summary(self) -> dict:
        result = []
        for player in (0, 1):
            visits = [v for v in self.visits if v.player == player]
            thrown = sum(v.darts for v in visits)
            scored = sum(0 if v.bust else v.score for v in visits)
            attempts = sum(v.checkout_attempts for v in visits)
            finishes = sum(v.checkout for v in visits)
            first9 = []
            for leg in set(v.leg_index for v in visits):
                leg_visits = [v for v in visits if v.leg_index == leg]
                # First 9 darts; if the leg ends earlier, use its actual dart count.
                used = 0; points = 0
                for v in leg_visits:
                    if used >= 9: break
                    take = min(9 - used, v.darts)
                    if take != v.darts: break  # can't infer score of partial visit
                    points += 0 if v.bust else v.score
                    used += take
                if used:
                    first9.append((points, used))
            lowdarts = 0
            lowdart_details = []
            highfinish_details = []
            highscore_details = []
            for v in visits:
                if v.checkout:
                    total = sum(x.darts for x in visits if x.leg_index == v.leg_index)
                    if 9 <= total <= 18:
                        lowdarts += 1
                        lowdart_details.append(total)
                    if v.score >= 100:
                        highfinish_details.append(v.score)
            highscore_details = [v.score for v in visits if v.score >= 171 and not v.bust]
            by_leg = []
            for leg in sorted({v.leg_index for v in self.visits}):
                lv = [v for v in visits if v.leg_index == leg]
                if not lv:
                    by_leg.append({'leg': leg + 1, 'darts': None, 'average': None, 'checkout': None})
                    continue
                darts_leg = sum(v.darts for v in lv)
                scored_leg = sum(0 if v.bust else v.score for v in lv)
                finishing = next((v for v in lv if v.checkout), None)
                by_leg.append({'leg': leg + 1, 'darts': darts_leg,
                               'average': round(scored_leg * 3 / darts_leg, 2) if darts_leg else 0,
                               'checkout': finishing.score if finishing else None})
            first_darts = {}
            for limit in (9, 12, 15, 18):
                total_score = total_darts = 0
                for leg in sorted({v.leg_index for v in visits}):
                    count = 0
                    for v in (x for x in visits if x.leg_index == leg):
                        if count + v.darts > limit:
                            break  # Individual dart scores are unavailable for partial visits.
                        total_score += 0 if v.bust else v.score
                        total_darts += v.darts
                        count += v.darts
                        if count == limit:
                            break
                first_darts[str(limit)] = round(3 * total_score / total_darts, 2) if total_darts else None
            scoring_bands = {str(t): sum(v.score >= t and not v.bust for v in visits)
                             for t in (60, 80, 100, 140, 180)}
            result.append({
                'player': self.names[player],
                'by_leg': by_leg, 'first_darts': first_darts, 'scoring_bands': scoring_bands,
                'average': round(scored / thrown * 3, 2) if thrown else 0,
                'first9': round(sum(p for p, d in first9) / sum(d for p, d in first9) * 3, 2) if first9 else 0,
                'checkout_percentage': round(finishes / attempts * 100, 2) if attempts else 0,
                'visits_95_plus': sum(v.score >= 95 and not v.bust for v in visits),
                'visits_133_plus': sum(v.score >= 133 and not v.bust for v in visits),
                'visits_171_plus': sum(v.score >= 171 and not v.bust for v in visits),
                'lowdarts': lowdarts,
                'bullfinishes': sum(v.bullfinish for v in visits),
                'highfinishes': sum(v.checkout and v.score >= 100 for v in visits),
                'highscores': len(highscore_details),
                'lowdart_details': lowdart_details,
                'highfinish_details': highfinish_details,
                'highscore_details': highscore_details,
                'bullfinish_details': [v.score for v in visits if v.bullfinish],
            })
        return {'done': self.done, 'legs': self.legs[:], 'sets': self.sets[:], 'players': result}
