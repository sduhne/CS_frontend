import sys
sys.path.insert(0, '.')
from rules_proto import *

def A(**kw):
    st = {i: 10000 for i in range(1, 7)}
    st.update(kw.pop('stacks', {}))
    return Hand(st, kw.pop('button', 1), 100, 200, **kw)

def show(tag, h, extra=''):
    s = h.summary()
    print(f"{tag}: street={s['street']} pot={s['pot']} to_act={s['to_act']} to_call={s['to_call']} minraise={s['min_raise_to']} stacks={s['stacks']} returned={h.returned} {extra}")

def run(h, script):
    for step in script.split(','):
        p = step.split()
        seat, kind = int(p[0]), p[1]
        to = float(p[2]) if len(p) > 2 else None
        if to is not None and to.is_integer(): to = int(to)
        h.act(seat, kind, to)

def expect_illegal(tag, fn):
    try:
        fn(); print(tag, 'NOT REJECTED')
    except Illegal as e:
        print(tag, 'rejected:', e)

# ---- positions
for n in range(2, 10):
    h = Hand({i: 5000 for i in range(1, n + 1)}, 1, 50, 100)
    print('P', n, [(s, h.labels()[s]) for s in h.order])
h = Hand({1: 5000, 2: 5000, 4: 5000, 5: 5000, 7: 5000, 8: 5000, 9: 5000}, 2, 50, 100)   # empty 3 and 6
print('P-empty', [(s, h.labels()[s]) for s in h.order])
h = Hand({1: 5000, 2: 5000, 4: 5000, 5: 5000}, 3, 50, 100)   # dead button on empty seat 3
print('P-dead', [(s, h.labels()[s]) for s in h.order])

# ---- T1 open, folds
h = A(); run(h, '4 raise 500,5 fold,6 fold,1 fold,2 fold'); show('T1a', h); run(h, '3 fold'); show('T1b', h)
# ---- T2 walk
h = A(); run(h, '4 fold,5 fold,6 fold,1 fold'); show('T2a', h); run(h, '2 fold'); show('T2b', h)
# ---- T3 limped pot, BB option
h = A(); run(h, '4 call,5 fold,6 fold,1 call,2 call'); show('T3a', h); run(h, '3 check'); show('T3b', h)
# ---- T4 min-raise chain
h = A(); run(h, '4 raise 500'); show('T4a', h); run(h, '5 raise 1300'); show('T4b', h)
expect_illegal('T4c', lambda: h.act(6, 'raise', 2000))
run(h, '6 raise 2100'); show('T4d', h)
# ---- T5 ante per player + bb ante
h = A(ante=25); show('T5a', h); print('   pots', h.pots())
h = A(bb_ante=200); show('T5b', h); print('   pots', h.pots(), 'dead', h.dead)
# ---- T6 short SB all-in on blind
h = A(stacks={2: 60}); show('T6a', h); run(h, '4 raise 500,5 fold,6 fold,1 fold'); show('T6b', h); run(h, '3 call'); show('T6c', h); print('   pots', h.pots())
# flop: 3 and 4 play on
run(h, '3 check,4 bet 600,3 fold'); show('T6d', h); print('   pots', h.pots())
h.award([[2]]); show('T6e', h); print('   ', h.result)
# ---- T7 short BB all-in on blind: full bb to call, refund
h = A(stacks={3: 120}); show('T7a', h); run(h, '4 fold,5 fold,6 fold,1 fold'); show('T7b', h); 
h = A(stacks={3: 120}); run(h, '4 call,5 fold,6 fold,1 fold,2 fold'); show('T7c', h); print('   pots', h.pots()); h.award([[3]]); show('T7d', h)
h = A(stacks={3: 120}); run(h, '4 call,5 fold,6 fold,1 call,2 fold'); show('T7e', h); print('   pots', h.pots())
# ---- T8 ante-only all-in (per-player ante 25, seat 5 has 20)
h = A(ante=25, stacks={5: 20}); show('T8a', h); run(h, '4 raise 500,6 fold,1 fold,2 fold,3 call'); show('T8b', h); print('   pots', h.pots())
# ---- T9 BB ante, BB short: ante first vs blind first (BB has 300, bb 200, bb_ante 200)
h = A(bb_ante=200, stacks={3: 300}); show('T9a ante_first', h); print('   pots', h.pots(), 'bb live', h.commit[3], 'dead', h.dead)
h = A(bb_ante=200, stacks={3: 300}, short_post='blind_first'); show('T9b blind_first', h); print('   pots', h.pots(), 'bb live', h.commit[3], 'dead', h.dead)
h = A(bb_ante=200, stacks={3: 150}); show('T9c ante_first bb150', h); print('   pots', h.pots(), 'bb live', h.commit[3], 'dead', h.dead)
run(h, '4 fold,5 fold,6 fold,1 fold'); show('T9d', h)
# ---- T10 incomplete all-in does not reopen
h = A(stacks={5: 700}); run(h, '4 raise 500,5 allin'); show('T10a', h); run(h, '6 fold,1 fold,2 fold,3 fold'); show('T10b', h)
expect_illegal('T10c', lambda: h.act(4, 'raise', 1500))
print('   may_raise 4:', h.may_raise(4)); run(h, '4 call'); show('T10d', h); print('   pots', h.pots())
# ---- T11 incomplete all-in, player behind not yet acted can raise: min raise-to
h = A(stacks={5: 700}); run(h, '4 raise 500,5 allin'); print('T11 min raise for 6:', h.min_raise_to(6), 'to_call', h.to_call(6))
run(h, '6 raise 1000'); show('T11b', h); run(h, '1 fold,2 fold,3 fold'); show('T11c', h); print('   may_raise 4:', h.may_raise(4), 'min', h.min_raise_to(4))
# ---- T12 cumulative short all-ins reopen
h = A(stacks={5: 700, 6: 850}); run(h, '4 raise 500,5 allin,6 allin'); show('T12a', h); run(h, '1 fold,2 fold,3 fold'); show('T12b', h); print('   may_raise 4:', h.may_raise(4), 'min', h.min_raise_to(4))
# ---- T13 call for less + side pot + different winners
h = A(stacks={1: 3000}); run(h, '4 raise 500,5 fold,6 fold,1 allin'); show('T13a', h); run(h, '2 fold,3 call'); show('T13b', h); run(h, '4 call'); show('T13c', h); print('   pots', h.pots())
run(h, '3 check,4 bet 2000,3 call'); show('T13d', h); run(h, '3 check,4 check,3 check,4 check'); show('T13e', h); print('   pots', h.pots())
import copy
h2 = copy.deepcopy(h); h2.award([[1], [4]]); show('T13f BTN best then LJ', h2)
h2 = copy.deepcopy(h); h2.award([[3]]); show('T13g BB wins all', h2)
h2 = copy.deepcopy(h)
expect_illegal('T13h only BTN named', lambda: h2.award([[1]]))
h2 = copy.deepcopy(h); h2.award([[1, 4], [3]]); show('T13i BTN and LJ tie', h2)
# ---- T14 uncalled all-in returned (hero shoves 10k into 3k)
h = A(stacks={3: 3000}); run(h, '4 fold,5 fold,6 fold,1 fold,2 allin'); show('T14a', h); run(h, '3 call'); show('T14b', h); print('   pots', h.pots())
h.award([[3]]); show('T14c', h)
# ---- T15 three all-ins, two side pots
h = A(stacks={4: 1000, 5: 2500, 6: 6000}); run(h, '4 allin,5 allin,6 allin,1 fold,2 fold,3 fold'); show('T15a', h); print('   pots', h.pots())
h2 = copy.deepcopy(h); h2.award([[4], [5], [6]]); show('T15b', h2)
h2 = copy.deepcopy(h); h2.award([[6]]); show('T15c', h2); print('   busted', h2.busted)
h2 = copy.deepcopy(h); h2.award([[4, 5], [6]]); show('T15d', h2)
# ---- T16 split with odd chip
h = Hand({1: 10000, 2: 10000, 3: 10000}, 1, 25, 50, ante=5); run(h, '1 raise 125,2 fold,3 call'); show('T16a', h); run(h, '3 check,1 check,3 check,1 check,3 check,1 check'); show('T16b', h); h.award([[1, 3]]); show('T16c', h)
# ---- T17 postflop order, check-raise min
h = A(); run(h, '4 raise 500,5 fold,6 fold,1 call,2 fold,3 call'); show('T17a', h); run(h, '3 check,4 bet 600,1 call'); show('T17b', h)
expect_illegal('T17c', lambda: h.act(3, 'raise', 1000))
run(h, '3 raise 1200'); show('T17d', h); run(h, '4 fold,1 call'); show('T17e', h)
# ---- T18 heads-up order
h = Hand({1: 3000, 2: 3000}, 1, 50, 100); show('T18a', h); print('   labels', h.labels()); run(h, '1 call,2 check'); show('T18b', h)
# ---- T19 heads-up SB shove bigger than BB stack
h = Hand({1: 3000, 2: 900}, 1, 50, 100); run(h, '1 allin'); show('T19a', h); run(h, '2 call'); show('T19b', h); h.award([[2]]); show('T19c', h)
# ---- T20 away player
h = A(away=[3]); run(h, '4 fold,5 fold,6 fold,1 fold'); show('T20a', h); run(h, '2 call'); show('T20b', h)
h = A(away=[3]); run(h, '4 fold,5 fold,6 fold,1 raise 400,2 fold'); show('T20c', h)
h = A(away=[2, 3]); run(h, '4 fold,5 fold,6 fold,1 fold'); show('T20d away sb and bb', h)
# ---- T21 runout: all-in and call preflop, no more actions
h = A(stacks={4: 4000}); run(h, '4 allin,5 fold,6 fold,1 fold,2 fold,3 call'); show('T21a', h)
expect_illegal('T21b', lambda: h.act(3, 'bet', 500))
h.award([[4]]); show('T21c', h)
# ---- T22 all-in on flop with a third player still to act; side betting continues
h = A(stacks={4: 2000}); run(h, '4 raise 500,5 fold,6 fold,1 call,2 fold,3 call'); run(h, '3 check,4 allin,1 call,3 call'); show('T22a', h); print('   pots', h.pots()); run(h, '3 bet 1000,1 fold'); show('T22b', h); print('   pots', h.pots())
h.award([[4], [3]]); show('T22c', h)
# ---- T23 raise more than stack rejected; act out of turn rejected; check facing bet rejected
h = A(stacks={4: 300})
expect_illegal('T23a', lambda: h.act(4, 'raise', 500))
expect_illegal('T23b', lambda: h.act(5, 'fold'))
expect_illegal('T23c', lambda: h.act(4, 'check'))
h.act(4, 'allin'); show('T23d', h)
# ---- T24 short all-in below the big blind (call for less preflop); BB has no decision when alone
h = A(stacks={4: 150}); run(h, '4 allin,5 fold,6 fold,1 fold,2 fold'); show('T24a', h); print('   pots', h.pots())
h = A(stacks={4: 150}); run(h, '4 allin,5 fold,6 fold,1 fold,2 call'); show('T24b', h)
# ---- T25 fold-out winner collects dead money of folded callers
h = A(); run(h, '4 raise 500,5 call,6 fold,1 fold,2 fold,3 call'); run(h, '3 check,4 bet 900,5 fold,3 fold'); show('T25', h)
# ---- T26 bb ante walk and steal
h = A(bb_ante=200); run(h, '4 fold,5 fold,6 fold,1 raise 450,2 fold,3 fold'); show('T26', h)
# ---- Spin
h = Hand({1: 300, 2: 300, 3: 300}, 1, 10, 20); show('S1', h); print('   labels', h.labels())
run(h, '1 allin,2 fold,3 call'); show('S1b', h); h.award([[1]]); show('S1c', h); print('   busted', h.busted)
h = Hand({1: 620, 2: 280}, 2, 15, 30); show('S2 HU', h); print('   labels', h.labels()); run(h, '2 allin,1 call'); show('S2b', h); h.award([[1]]); show('S2c', h); print('   busted', h.busted)
h = Hand({1: 300, 2: 300, 3: 300}, 1, 10, 20); run(h, '1 fold,2 call'); show('S3 sb limp', h); run(h, '3 allin'); show('S3b', h); run(h, '2 fold'); show('S3c', h)
h = Hand({1: 450, 2: 150, 3: 300}, 1, 20, 40); run(h, '1 raise 80,2 allin,3 allin'); show('S4', h); run(h, '1 call'); show('S4b', h); print('   pots', h.pots()); h.award([[2], [1]]); show('S4c', h)
# ---- AoF (amounts in bb; sb 0.5 bb 1; fee 0.1)
def aof(st=None, button=1, fee=0.1):
    stacks = {1: 8.0, 2: 8.0, 3: 8.0, 4: 8.0}
    stacks.update(st or {})
    return Hand(stacks, button, 0.5, 1.0, allin_or_fold=True, fee=fee)
h = aof(); show('F1', h); print('   labels', h.labels())
expect_illegal('F1b', lambda: h.act(4, 'call'))
expect_illegal('F1c', lambda: h.act(4, 'raise', 2.5))
run(h, '4 fold,1 fold,2 fold'); show('F2 walk', h); print('   fee', h.fee_taken)
h = aof(); run(h, '4 fold,1 allin,2 fold,3 fold'); show('F3 steal', h); print('   fee', h.fee_taken)
h = aof(); run(h, '4 allin,1 fold,2 fold,3 allin'); show('F4', h); h.award([[4]]); show('F4b', h); print('   fee', h.fee_taken, 'busted', h.busted)
h = aof({2: 5.5}); run(h, '4 allin,1 allin,2 allin,3 fold'); show('F5', h); print('   pots', h.pots()); h.award([[2], [1]]); show('F5b', h); print('   fee', h.fee_taken)
h = aof({2: 5.5}); run(h, '4 fold,1 fold,2 allin,3 allin'); show('F6', h); h.award([[2], [3]]); show('F6b', h); print('   fee', h.fee_taken)
