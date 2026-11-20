import random, sys
sys.path.insert(0, '.')
from rules_proto import Hand, Illegal

def one(rng):
    n = rng.randint(2, 9)
    bb = rng.choice([20, 100, 200, 2000])
    stacks = {s: rng.choice([1, bb // 2, bb, bb + 5, 3 * bb, 12 * bb, 40 * bb, 100 * bb]) for s in range(1, n + 1)}
    kind = rng.choice(['none', 'player', 'bb'])
    h = Hand(stacks, rng.randint(1, n), bb // 2, bb, ante=bb // 8 if kind == 'player' else 0,
             bb_ante=bb if kind == 'bb' else 0, away=[s for s in stacks if rng.random() < 0.1],
             short_post=rng.choice(['ante_first', 'blind_first']))
    total = sum(stacks.values())
    steps = 0
    while h.street not in ('showdown', 'done'):
        s = h.to_act()
        assert s is not None, 'no actor but hand open'
        assert sum(h.stack.values()) + h.pot_total() == total, 'chips not conserved'
        owe = h.owe(s)
        opts = ['fold'] if owe > 0 else ['check']
        if owe > 0:
            opts += ['call', 'call']
        if h.may_raise(s):
            opts += ['raise', 'allin']
        else:
            opts += ['allin'] if owe > 0 else []
        k = rng.choice(opts)
        if k == 'raise':
            lo = h.min_raise_to(s)
            hi = h.street_commit[s] + h.stack[s]
            to = rng.randint(lo, hi) if hi > lo else hi
            h.act(s, 'raise' if h.bet_to > 0 or h.street == 'preflop' else 'bet', to)
        else:
            h.act(s, k)
        steps += 1
        assert steps < 500, 'loop'
    assert sum(h.stack.values()) + (h.pot_total() if h.street == 'showdown' else 0) == total, 'end conservation'
    if h.street == 'showdown':
        live = h.live()
        rng.shuffle(live)
        h.award([[x] for x in live])
        assert sum(h.stack.values()) == total, 'award conservation'
        assert sum(p['amount'] for p in h.result['pots']) == sum(h.result['won'].values())
    return h

rng = random.Random(7)
sd = 0
for i in range(40000):
    try:
        h = one(rng)
    except Illegal as e:
        print('illegal in fuzz', e); raise
    sd += h.result is not None
print('ok, hands', 40000)
