"""Pure competition rules; no persistence, I/O or TFL dependencies."""
from math import pow

KINDS = ('league', 'cup', 'ladder', 'vm', 'training_tournament', 'final_tournament')

def elo_change(own, other, score, k=64):
    if score not in (0, 0.5, 1):
        raise ValueError('Invalid Elo outcome')
    exp = 1 / (1 + pow(10, (other - own) / 400))
    return round(k * (score-exp), 3), round(exp, 7)

def mode_rules(kind, phase, final=False, overrides=None):
    rules = {
        'start_score':501, 'double_out':True, 'mode':'legs',
        'max_legs':6, 'allow_draw':True,
        'best_of_sets':3, 'best_of_legs_per_set':3,
    }
    if kind == 'vm':
        rules.update(mode='sets' if phase == 'knockout' else 'legs',
                     max_legs=5, allow_draw=False, best_of_sets=5 if final else 3,
                     best_of_legs_per_set=3)
    if kind == 'cup' and phase == 'knockout':
        rules.update(mode='sets', allow_draw=False, best_of_sets=3,
                     best_of_legs_per_set=3)
    if kind == 'ladder':
        rules.update(max_legs=6, allow_draw=True)
    if phase == 'knockout': rules['allow_draw'] = False
    rules.update(overrides or {})
    if rules['mode'] not in ('legs','sets'):
        raise ValueError('Unknown scorer mode')
    if not 1 <= int(rules['max_legs']) <= 101: raise ValueError('Invalid legs')
    if rules['mode'] == 'sets' and (int(rules['best_of_sets'])%2 != 1 or int(rules['best_of_legs_per_set'])%2 != 1):
        raise ValueError('Sets and legs per set must be odd')
    return rules

def round_robin(ids, double_round=False):
    ids = list(dict.fromkeys(ids))
    if len(ids) < 2: return []
    if len(ids) % 2: ids.append(None)
    n=len(ids); fixtures=[]
    for r in range(n-1):
        for a in range(n//2):
            x,y=ids[a],ids[n-1-a]
            if x is not None and y is not None:
                if r%2: x,y=y,x
                fixtures.append((r+1,x,y))
        ids=[ids[0],ids[-1],*ids[1:-1]]
    if double_round:
        fixtures += [(r+n-1,y,x) for r,x,y in fixtures[:]]
    return fixtures

def rank_rows(matches, players, point_win=2, point_draw=1):
    rows={p:{'player_id':p,'played':0,'wins':0,'draws':0,'losses':0,'points':0,'legs_for':0,'legs_against':0,'sets_for':0,'sets_against':0} for p in players}
    for m in matches:
        a,b=m['player1_id'],m['player2_id']
        if a not in rows or b not in rows or m['status']!='finished': continue
        x,y=int(m['legs1'] or 0),int(m['legs2'] or 0)
        sx,sy=int(m.get('sets1') or 0),int(m.get('sets2') or 0)
        for me,sc,against,ss,sa in ((a,x,y,sx,sy),(b,y,x,sy,sx)):
            d=rows[me];d['played']+=1;d['legs_for']+=sc;d['legs_against']+=against;d['sets_for']+=ss;d['sets_against']+=sa
            if (sx,sy)!=(0,0): sc,against=ss,sa
            if sc>against:d['wins']+=1;d['points']+=point_win
            elif sc==against:d['draws']+=1;d['points']+=point_draw
            else:d['losses']+=1
    return sorted(rows.values(),key=lambda r:(-r['points'],-(r['legs_for']-r['legs_against']),-r['legs_for'],str(r['player_id'])))

def bracket_pairs(seeded_ids):
    p=list(seeded_ids)
    if len(p)<2:return []
    n=1<<(len(p)-1).bit_length()
    # Standard seeding distributes top-ranked competitors across bracket halves.
    positions=[1,2]
    while len(positions)<n:
        total=2*len(positions)+1
        positions=[x for seed in positions for x in (seed,total-seed)]
    assigned={i+1:pid for i,pid in enumerate(p)}
    return [(assigned.get(positions[i]),assigned.get(positions[i+1])) for i in range(0,n,2)]
