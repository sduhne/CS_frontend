import sys, copy
sys.path.insert(0, '.')
from rules_proto import *
from rules_cases import A, show, run, expect_illegal
print('=' * 30)
h = A(stacks={5: 700, 6: 850}); run(h, '4 raise 500,5 allin,6 allin,1 call,2 fold,3 fold'); show('T12x', h); print('   may_raise 4:', h.may_raise(4), 'min', h.min_raise_to(4))
run(h, '4 call'); show('T12y', h); print('  pots', h.pots())
# odd chip
h = Hand({1: 10000, 2: 10000, 3: 10000}, 1, 25, 50); run(h, '1 raise 125,2 fold,3 call'); run(h, '3 check,1 check,3 check,1 check,3 check,1 check'); show('T27a', h); h.award([[1, 3]]); show('T27b', h)
# 8 players antes
h = Hand({i: 40000 for i in range(1, 9)}, 1, 1000, 2000, ante=250); show('T28a', h); print(h.labels())
h = Hand({i: 40000 for i in range(1, 9)}, 1, 1000, 2000, bb_ante=2000); show('T28b', h)
# BB exactly the blind: all-in, no option
h = A(stacks={3: 200}); run(h, '4 call,5 fold,6 fold,1 fold,2 call'); show('T29', h); print('  pots', h.pots())
# all-in exactly a min-raise reopens
h = A(stacks={5: 800}); run(h, '4 raise 500,5 allin,6 fold,1 fold,2 fold,3 fold'); show('T30', h); print('   may_raise 4:', h.may_raise(4))
# hmm: nobody could call a raise (5 all-in) -> may_raise False; use a caller
h = A(stacks={5: 800}); run(h, '4 raise 500,5 allin,6 call,1 fold,2 fold,3 fold'); show('T30b', h); print('   may_raise 4:', h.may_raise(4), h.min_raise_to(4))
# postflop bet below bb
h = A(); run(h, '4 call,5 fold,6 fold,1 fold,2 call,3 check')
expect_illegal('T31a', lambda: h.act(2, 'bet', 150))
run(h, '2 bet 200'); show('T31b', h)
# SB completes, BB raises, SB may re-raise
h = A(); run(h, '4 fold,5 fold,6 fold,1 fold,2 call,3 raise 600'); show('T32', h); print('  may', h.may_raise(2))
# per-player ante, short stack ante+partial blind in BB
h = A(ante=25, stacks={3: 100}); show('T33', h); run(h, '4 call,5 fold,6 fold,1 fold,2 fold'); show('T33b', h); print('  pots', h.pots()); h.award([[3]]); show('T33c', h)
# button on seat 2 with seats 1,2,4,5 (3 empty): next button 4
print(order_from_button([1, 2, 4, 5], 4), 'labels', LABELS[4])
# HU after bust: seats 1,3 button 3
print(order_from_button([1, 3], 3))
# conservation check
h = A(ante=25, stacks={5: 20, 2: 60, 3: 3000}); tot = sum(h.start.values()); run(h, '4 raise 500,6 call,1 allin,3 allin,4 call,6 fold'); show('T34', h); print('  pots', h.pots()); 
print('  total', sum(h.stack.values()) + h.pot_total(), tot)
h.award([[5], [2], [3], [1], [4]]); show('T34b', h); print('  total', sum(h.stack.values()), tot)
