"""Asserts the numbers printed in section 9 of proposal-rules.md against the reference model."""
import copy, sys
sys.path.insert(0, '.')
from rules_proto import Hand, Illegal, order_from_button, LABELS

def A(**kw):
    st = {i: 10000 for i in range(1, 7)}
    st.update(kw.pop('stacks', {}))
    return Hand(st, kw.pop('button', 1), 100, 200, **kw)

def run(h, script):
    for step in script.split(','):
        p = step.split()
        to = float(p[2]) if len(p) > 2 else None
        h.act(int(p[0]), p[1], int(to) if to is not None and to.is_integer() else to)
    return h

def bad(fn):
    try:
        fn()
    except Illegal:
        return True
    return False

LJ, HJ, CO, BTN, SB, BB = 4, 5, 6, 1, 2, 3
def pots(h): return [(p['amount'], p['eligible']) for p in h.pots()]

h = A(); s = h.summary(); assert (s['pot'], s['to_act'], s['to_call'], s['min_raise_to']) == (300, LJ, 200, 400)       # 1
assert order_from_button([1, 2, 4, 5], 4) == [2, 4, 5, 1]                                                              # 2
h = Hand({1: 3000, 2: 3000}, 1, 50, 100); s = h.summary(); assert (s['to_act'], s['to_call'], s['min_raise_to']) == (1, 50, 200)
run(h, '1 call,2 check'); s = h.summary(); assert (s['street'], s['pot'], s['to_act']) == ('flop', 200, 2)             # 3
assert order_from_button([1, 3], 3) == [3, 1]                                                                          # 4
h = A(ante=25); assert h.pot_total() == 450 and (h.stack[LJ], h.stack[SB], h.stack[BB]) == (9975, 9875, 9775)          # 5
h = A(stacks={3: 120}); s = h.summary(); assert (s['to_call'], s['min_raise_to']) == (200, 400)
run(h, '4 fold,5 fold,6 fold,1 fold'); s = h.summary(); assert (s['to_act'], s['to_call'], s['min_raise_to']) == (SB, 20, None)   # 6
h = run(A(stacks={3: 120}), '4 call,5 fold,6 fold,1 fold,2 fold'); assert h.street == 'showdown' and h.returned == {LJ: 80} and h.pot_total() == 340
h.award([[BB]]); assert (h.stack[BB], h.stack[LJ]) == (340, 9880)                                                      # 7
h = run(A(ante=25, stacks={5: 20}), '4 raise 500,6 fold,1 fold,2 fold,3 call'); assert pots(h) == [(120, [LJ, HJ, BB]), (1125, [LJ, BB])]   # 8
h = A(bb_ante=200, stacks={3: 300}); assert (h.dead, h.commit[BB], h.pot_total()) == (200, 100, 400)
h = A(bb_ante=200, stacks={3: 300}, short_post='blind_first'); assert (h.dead, h.commit[BB], h.pot_total()) == (100, 200, 400)   # 9
h = run(A(bb_ante=200, stacks={3: 150}), '4 fold,5 fold,6 fold,1 fold'); assert h.street == 'showdown' and h.returned == {SB: 100} and h.pot_total() == 150   # 10
h = run(A(ante=25, stacks={3: 100}), '4 call,5 fold,6 fold,1 fold,2 fold'); assert h.returned == {LJ: 100} and pots(h) == [(375, [LJ, BB]), (50, [LJ])]
h.award([[BB]]); assert (h.stack[BB], h.stack[LJ]) == (375, 9925)                                                      # 11
h = run(A(), '4 raise 500,5 fold,6 fold,1 fold,2 fold'); s = h.summary(); assert (s['pot'], s['to_call'], s['min_raise_to']) == (800, 300, 800)
run(h, '3 fold'); assert h.stack[LJ] == 10300                                                                          # 12
h = run(A(), '4 call,5 fold,6 fold,1 call,2 call'); s = h.summary(); assert (s['to_act'], s['to_call'], s['min_raise_to']) == (BB, 0, 400)
run(h, '3 check'); s = h.summary(); assert (s['street'], s['pot'], s['to_act']) == ('flop', 800, SB)                   # 13
h = run(A(), '4 raise 500,5 raise 1300'); s = h.summary(); assert (s['to_call'], s['min_raise_to']) == (1300, 2100)
assert bad(lambda: h.act(CO, 'raise', 2000)); run(h, '6 raise 2100'); s = h.summary(); assert (s['min_raise_to'], s['pot']) == (2900, 4200)   # 14
h = run(A(stacks={5: 700}), '4 raise 500,5 allin'); s = h.summary(); assert (s['to_call'], s['min_raise_to']) == (700, 1000)
run(h, '6 fold,1 fold,2 fold,3 fold'); assert h.to_call() == 200 and bad(lambda: h.act(LJ, 'raise', 1500))
run(h, '4 call'); assert h.street == 'showdown' and h.pot_total() == 1700                                              # 15
h = run(A(stacks={5: 700}), '4 raise 500,5 allin,6 raise 1000,1 fold,2 fold,3 fold'); assert (h.to_call(), h.may_raise(LJ), h.min_raise_to(LJ)) == (500, True, 1300)   # 16
h = run(A(stacks={5: 700, 6: 850}), '4 raise 500,5 allin,6 allin,1 call,2 fold,3 fold'); assert (h.to_call(), h.may_raise(LJ), h.min_raise_to(LJ)) == (350, True, 1150)
run(h, '4 call'); assert [p[0] for p in pots(h)] == [3100, 450]                                                        # 17
h = A(stacks={4: 300}); assert bad(lambda: h.act(LJ, 'raise', 500)) and bad(lambda: h.act(HJ, 'fold')) and bad(lambda: h.act(LJ, 'check'))
h.act(LJ, 'allin'); s = h.summary(); assert (s['to_call'], s['min_raise_to']) == (300, 500)                            # 18
h = run(A(stacks={4: 150}), '4 allin,5 fold,6 fold,1 fold,2 fold'); assert h.street == 'showdown' and h.returned == {BB: 50} and h.pot_total() == 400   # 19
h = run(A(), '4 raise 500,5 fold,6 fold,1 call,2 fold,3 call,3 check,4 bet 600,1 call'); assert h.min_raise_to(BB) == 1200 and bad(lambda: h.act(BB, 'raise', 1000))
run(h, '3 raise 1200,4 fold,1 call'); s = h.summary(); assert (s['street'], s['pot']) == ('turn', 4600)                # 20
h = run(A(stacks={1: 3000}), '4 raise 500,5 fold,6 fold,1 allin,2 fold,3 call,4 call'); assert h.pot_total() == 9100
run(h, '3 check,4 bet 2000,3 call,3 check,4 check,3 check,4 check'); assert [p[0] for p in pots(h)] == [9100, 4000]    # 21
g = copy.deepcopy(h); g.award([[BTN], [LJ]]); assert (g.stack[BTN], g.stack[LJ], g.stack[BB]) == (9100, 9000, 5000)
g = copy.deepcopy(h); g.award([[BB]]); assert g.stack[BB] == 18100 and g.busted == [BTN]                               # 22
g = copy.deepcopy(h); assert bad(lambda: g.award([[BTN]]))
g = copy.deepcopy(h); g.award([[BTN, LJ], [BB]]); assert (g.stack[BTN], g.stack[LJ]) == (4550, 13550)                  # 23
h = run(A(stacks={3: 3000}), '4 fold,5 fold,6 fold,1 fold,2 allin'); assert h.to_call() == 2800
run(h, '3 call'); assert h.returned == {SB: 7000} and h.pot_total() == 6000 and h.street == 'showdown' and bad(lambda: h.act(BB, 'bet', 500))
h.award([[BB]]); assert (h.stack[BB], h.stack[SB]) == (6000, 7000)                                                     # 24
h = run(A(stacks={4: 1000, 5: 2500, 6: 6000}), '4 allin,5 allin,6 allin,1 fold,2 fold,3 fold'); assert h.returned == {CO: 3500} and [p[0] for p in pots(h)] == [3300, 3000]
g = copy.deepcopy(h); g.award([[LJ], [HJ], [CO]]); assert (g.stack[LJ], g.stack[HJ], g.stack[CO]) == (3300, 3000, 3500)   # 25
g = copy.deepcopy(h); g.award([[CO]]); assert g.stack[CO] == 9800 and g.busted == [LJ, HJ]
g = copy.deepcopy(h); g.award([[LJ, HJ], [CO]]); assert (g.stack[LJ], g.stack[HJ]) == (1650, 4650)                     # 26
h = run(Hand({1: 10000, 2: 10000, 3: 10000}, 1, 25, 50), '1 raise 125,2 fold,3 call,3 check,1 check,3 check,1 check,3 check,1 check')
assert h.pot_total() == 275; h.award([[1, 3]]); assert (h.stack[3] - 9875, h.stack[1] - 9875) == (138, 137)            # 27
h = run(A(stacks={2: 60}), '4 raise 500,5 fold,6 fold,1 fold,3 call,3 check,4 bet 600,3 fold'); assert h.street == 'showdown' and h.returned == {LJ: 600}
assert pots(h) == [(180, [LJ, SB]), (880, [LJ])]; h.award([[SB]]); assert (h.stack[SB], h.stack[LJ]) == (180, 10380)   # 28
h = run(A(stacks={4: 2000}), '4 raise 500,5 fold,6 fold,1 call,2 fold,3 call,3 check,4 allin,1 call,3 call'); s = h.summary(); assert (s['street'], s['pot'], s['to_act']) == ('turn', 6100, BB)
run(h, '3 bet 1000,1 fold'); assert h.returned == {BB: 1000} and h.street == 'showdown'                                # 29
h = run(A(bb_ante=200), '4 fold,5 fold,6 fold,1 raise 450,2 fold,3 fold'); assert h.stack[BTN] == 10500                # 30
h = run(A(away=[3]), '4 fold,5 fold,6 fold,1 raise 400,2 fold'); assert h.street == 'done' and h.stack[BTN] == 10300
h = run(A(away=[3]), '4 fold,5 fold,6 fold,1 fold,2 call'); assert h.street == 'flop'                                  # 32
h = run(A(), '4 raise 500,5 raise 900'); h.act(CO, 'raise', 2100)                                                      # 36 a
h = run(A(), '4 raise 500,5 raise 1900'); assert bad(lambda: h.act(CO, 'raise', 2100))                                 # 36 b
h = run(Hand({1: 300, 2: 300, 3: 300}, 1, 10, 20), '1 allin,2 fold,3 call'); h.award([[1]]); assert h.stack[1] == 610 and h.busted == [3]   # 38
h = run(Hand({1: 620, 2: 280}, 2, 15, 30), '2 allin,1 call'); h.award([[1]]); assert h.stack[1] == 900                 # 39
h = run(Hand({1: 300, 2: 300, 3: 300}, 1, 10, 20), '1 fold,2 call,3 allin'); assert h.to_call() == 280; run(h, '2 fold'); assert h.stack[3] == 320   # 40
h = run(Hand({1: 450, 2: 150, 3: 300}, 1, 20, 40), '1 raise 80,2 allin,3 allin'); assert h.to_call() == 220 and not h.may_raise(1)
run(h, '1 call'); assert [p[0] for p in pots(h)] == [450, 300]; h.award([[2], [1]]); assert (h.stack[2], h.stack[1]) == (450, 450)   # 41
def aof(st=None):
    stacks = {1: 8.0, 2: 8.0, 3: 8.0, 4: 8.0}; stacks.update(st or {})
    return Hand(stacks, 1, 0.5, 1.0, allin_or_fold=True, fee=0.1)
h = aof(); assert h.pot_total() == 1.5 and bad(lambda: h.act(4, 'raise', 2.5)); run(h, '4 fold,1 fold,2 fold'); assert abs(h.stack[3] - 8.4) < 1e-9   # 42
h = run(aof(), '4 fold,1 allin,2 fold,3 fold'); assert abs(h.stack[1] - 9.4) < 1e-9                                    # 43
h = run(aof({2: 5.5}), '4 allin,1 allin,2 allin,3 fold'); assert [p[0] for p in pots(h)] == [17.5, 5.0]
h.award([[2], [1]]); assert abs(h.stack[2] - 17.4) < 1e-9 and h.stack[1] == 5.0                                        # 44
h = run(aof({2: 5.5}), '4 fold,1 fold,2 allin,3 call'); assert h.events[-1][2:] == ('call', 5.5) and h.pot_total() == 11.0
h.award([[2], [3]]); assert abs(h.stack[2] - 10.9) < 1e-9 and h.stack[3] == 2.5                                        # 45
print('all section 9 numbers confirmed')
