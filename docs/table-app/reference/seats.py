"""Check the seat slot tables: pods, bet chips, dealer buttons and the centre block never overlap."""
import itertools, sys

# slot = (side, position %). side T/B: position is the x centre; side L/R: the y centre.
# Hero is always first (bottom centre); then clockwise, i.e. to hero's left, as poker clients draw it.
SLOTS = {
 2: [('B', 50), ('T', 50)],
 3: [('B', 50), ('T', 25), ('T', 75)],
 4: [('B', 50), ('L', 46), ('T', 50), ('R', 46)],
 5: [('B', 50), ('L', 58), ('T', 28), ('T', 72), ('R', 58)],
 6: [('B', 50), ('L', 66), ('L', 34), ('T', 50), ('R', 34), ('R', 66)],
 7: [('B', 50), ('L', 66), ('L', 35), ('T', 35), ('T', 65), ('R', 35), ('R', 66)],
 8: [('B', 50), ('B', 11), ('L', 52), ('T', 22), ('T', 50), ('T', 78), ('R', 52), ('B', 89)],
 9: [('B', 50), ('B', 11), ('L', 60), ('L', 34), ('T', 35), ('T', 65), ('R', 34), ('R', 60), ('B', 89)],
}

SIZES = {
 # table (w,h), pod (w,h), hero pod (w,h), board card (w,h), board gap, pot line h, chip (w,h), dealer d
 'narrow 560':  ((528, 304), (100, 56), (184, 68), (36, 50), 4, 26, (52, 22), 18),
 'medium 1024': ((616, 360), (112, 60), (216, 80), (44, 62), 6, 30, (60, 24), 20),
 'wide 1440':   ((928, 460), (152, 80), (280, 104), (56, 78), 8, 36, (76, 28), 24),
}

def rect(cx, cy, w, h): return (cx - w/2, cy - h/2, cx + w/2, cy + h/2)
def hit(a, b, pad=0):
    return a[0] < b[2] + pad and b[0] < a[2] + pad and a[1] < b[3] + pad and b[1] < a[3] + pad

def layout(n, size):
    (W, H), (pw, ph), (hw, hh), (cw, ch), cg, potH, (bw, bh), dd = SIZES[size]
    pods, chips, deals = [], [], []
    cx0, cy0 = W/2, H*0.46
    for i, (side, pos) in enumerate(SLOTS[n]):
        w, h = (hw, hh) if i == 0 else (pw, ph)
        if side == 'T': p = rect(pos/100*W, h/2, w, h)
        if side == 'B': p = rect(pos/100*W, H - h/2, w, h)
        if side == 'L': p = rect(w/2, pos/100*H, w, h)
        if side == 'R': p = rect(W - w/2, pos/100*H, w, h)
        pods.append(p)
        mx, my = (p[0]+p[2])/2, (p[1]+p[3])/2
        if side == 'T': c = rect(mx, p[3] + 6 + bh/2, bw, bh)
        if side == 'B': c = rect(mx, p[1] - 6 - bh/2, bw, bh)
        if side == 'L': c = rect(p[2] + 6 + bw/2, my, bw, bh)
        if side == 'R': c = rect(p[0] - 6 - bw/2, my, bw, bh)
        chips.append(c)
        # dealer button straddles the pod corner nearest the table centre (ties: the right-hand corner)
        kx = p[0] if mx > cx0 else p[2]
        ky = p[1] if my > cy0 else p[3]
        deals.append(rect(kx, ky, dd, dd))
    bwid = 5*cw + 4*cg
    blockH = potH + 6 + ch
    top = cy0 - blockH/2
    pot = (cx0 - 90, top, cx0 + 90, top + potH)
    board = (cx0 - bwid/2, top + potH + 6, cx0 + bwid/2, top + blockH)
    return (W, H), pods, pot, board, chips, deals

def check(n, size, verbose=False):
    (W, H), pods, pot, board, chips, deals = layout(n, size)
    bad = []
    for (i, a), (j, b) in itertools.combinations(enumerate(pods), 2):
        if hit(a, b, 6): bad.append('pod %d / pod %d' % (i+1, j+1))
    for i, p in enumerate(pods):
        if p[0] < -0.01 or p[1] < -0.01 or p[2] > W + 0.01 or p[3] > H + 0.01: bad.append('pod %d outside' % (i+1))
        if hit(p, board, 4) or hit(p, pot, 4): bad.append('pod %d / centre' % (i+1))
    for i, c in enumerate(chips):
        if hit(c, board, 3) or hit(c, pot, 3): bad.append('chip %d / centre' % (i+1))
        for j, p in enumerate(pods):
            if hit(c, p, 3): bad.append('chip %d / pod %d' % (i+1, j+1))
        for j, c2 in enumerate(chips):
            if j > i and hit(c, c2, 3): bad.append('chip %d / chip %d' % (i+1, j+1))
    for i, d in enumerate(deals):
        for j, c in enumerate(chips):
            if hit(d, c, 1): bad.append('dealer %d / chip %d' % (i+1, j+1))
        if hit(d, board, 1) or hit(d, pot, 1): bad.append('dealer %d / centre' % (i+1))
        for j, p in enumerate(pods):
            if j != i and hit(d, p, 1): bad.append('dealer %d / pod %d' % (i+1, j+1))
        for j, d2 in enumerate(deals):
            if j > i and hit(d, d2, 1): bad.append('dealer %d / dealer %d' % (i+1, j+1))
    if verbose:
        print(size, n, 'pot', [round(v) for v in pot], 'board', [round(v) for v in board])
        for i in range(n):
            print('  pod', i+1, [round(v) for v in pods[i]], 'chip', [round(v) for v in chips[i]], 'D', [round(v) for v in deals[i]])
    return bad

if __name__ == '__main__':
    ok = True
    for size in SIZES:
        for n in SLOTS:
            bad = check(n, size, verbose=('-v' in sys.argv))
            print('%-12s %d seats: %s' % (size, n, 'ok' if not bad else '; '.join(bad)))
            ok &= not bad
    print('ALL OK' if ok else 'PROBLEMS')
