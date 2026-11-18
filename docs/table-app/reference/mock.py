"""Static mock of the table coach in the menlo.bet brand, to check the numbers in the proposal.

python3 mock.py <fonts dir> <out.html> [mode] [seats]
"""
import sys

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
ORDER = {
    2: ['BTN/SB', 'BB'], 3: ['BTN', 'SB', 'BB'], 4: ['CO', 'BTN', 'SB', 'BB'],
    5: ['HJ', 'CO', 'BTN', 'SB', 'BB'], 6: ['LJ', 'HJ', 'CO', 'BTN', 'SB', 'BB'],
    7: ['UTG', 'LJ', 'HJ', 'CO', 'BTN', 'SB', 'BB'],
    8: ['UTG', 'UTG+1', 'LJ', 'HJ', 'CO', 'BTN', 'SB', 'BB'],
    9: ['UTG', 'UTG+1', 'UTG+2', 'LJ', 'HJ', 'CO', 'BTN', 'SB', 'BB'],
}

SUITS = """
<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs>
<symbol id="s" viewBox="0 0 24 24"><path d="M12 2.5C8.2 6.8 3 10 3 14.2a4.4 4.4 0 0 0 7.9 2.7L9.6 21.5h4.8l-1.3-4.6A4.4 4.4 0 0 0 21 14.2C21 10 15.8 6.8 12 2.5z"/></symbol>
<symbol id="h" viewBox="0 0 24 24"><path d="M12 21C7.5 16.6 3 13.2 3 8.6A4.6 4.6 0 0 1 12 7a4.6 4.6 0 0 1 9 1.6c0 4.6-4.5 8-9 12.4z"/></symbol>
<symbol id="d" viewBox="0 0 24 24"><path d="M12 2.5 19.5 12 12 21.5 4.5 12z"/></symbol>
<symbol id="c" viewBox="0 0 24 24"><path d="M12 2.5a4.2 4.2 0 0 1 3.3 6.8 4.2 4.2 0 1 1-2.2 7.3l1.3 4.9H9.6l1.3-4.9a4.2 4.2 0 1 1-2.2-7.3A4.2 4.2 0 0 1 12 2.5z"/></symbol>
</defs></svg>
"""

CSS = r"""
@font-face{font-family:"Barlow Semi Condensed";font-weight:700;font-style:normal;font-display:swap;src:url(FONTS/barlow-semi-condensed-latin-700-normal.woff2) format("woff2")}
@font-face{font-family:"Barlow Semi Condensed";font-weight:800;font-style:normal;font-display:swap;src:url(FONTS/barlow-semi-condensed-latin-800-normal.woff2) format("woff2")}
@font-face{font-family:"Barlow Semi Condensed";font-weight:800;font-style:italic;font-display:swap;src:url(FONTS/barlow-semi-condensed-latin-800-italic.woff2) format("woff2")}
@font-face{font-family:Inter;font-weight:400;font-display:swap;src:url(FONTS/inter-latin-400-normal.woff2) format("woff2")}
@font-face{font-family:Inter;font-weight:500;font-display:swap;src:url(FONTS/inter-latin-500-normal.woff2) format("woff2")}
@font-face{font-family:Inter;font-weight:600;font-display:swap;src:url(FONTS/inter-latin-600-normal.woff2) format("woff2")}
@font-face{font-family:Inter;font-weight:700;font-display:swap;src:url(FONTS/inter-latin-700-normal.woff2) format("woff2")}
@font-face{font-family:"MB Display Fallback";font-weight:700 800;src:local("Arial Bold"),local("Arial-BoldMT"),local("Liberation Sans Bold");size-adjust:83%;ascent-override:120.5%;descent-override:24.1%;line-gap-override:0%}
@font-face{font-family:"MB Display Fallback";font-weight:800;font-style:italic;src:local("Arial Bold Italic"),local("Arial-BoldItalicMT"),local("Liberation Sans Bold Italic");size-adjust:77%;ascent-override:130%;descent-override:26%;line-gap-override:0%}
@font-face{font-family:"MB Body Fallback";src:local("Arial"),local("ArialMT"),local("Liberation Sans");size-adjust:107.5%;ascent-override:90.1%;descent-override:22.4%;line-gap-override:0%}
:root{
  --ink:#0A0A0B;--panel:#151518;--line:#26262B;--line-strong:#3A3A42;
  --yellow:#FFD60A;--yellow-hover:#E6B800;--yellow-wash:rgba(255,214,10,.08);--yellow-tint:rgba(255,214,10,.18);
  --white:#FFFFFF;--soft:#C9C9D1;--grey:#9A9AA3;
  --win:#3DDC84;--loss:#FF5C5C;--win-tint:rgba(61,220,132,.18);--loss-tint:rgba(255,92,92,.18);
  --display:"Barlow Semi Condensed","MB Display Fallback","Arial Narrow",Arial,sans-serif;
  --body:Inter,"MB Body Fallback",system-ui,"Segoe UI",Arial,sans-serif;
  --r-card:16px;--r-tile:14px;--r-btn:14px;--r-ctl:12px;--r-in:10px;--r-pill:999px;
  --gut:16px;--gap:8px;
  --pod-w:100px;--pod-h:56px;--hero-w:184px;--hero-h:68px;--table-h:304px;
  --pos:18px;--stack:17px;--card-w:36px;--card-h:50px;--hcard-w:40px;--hcard-h:56px;
  --chip-h:22px;--chip-f:13px;--deal:18px;--verb:64px;--size:28px;
}
@media (min-width:1024px){:root{--gut:16px;--gap:12px;--pod-w:112px;--pod-h:60px;--hero-w:216px;--hero-h:80px;--table-h:360px;
  --pos:20px;--stack:18px;--card-w:44px;--card-h:62px;--hcard-w:48px;--hcard-h:66px;--chip-h:24px;--chip-f:14px;--deal:20px;--verb:88px;--size:32px}}
@media (min-width:1280px){:root{--gut:24px;--gap:16px;--pod-w:152px;--pod-h:80px;--hero-w:280px;--hero-h:104px;--table-h:460px;
  --pos:26px;--stack:22px;--card-w:56px;--card-h:78px;--hcard-w:64px;--hcard-h:88px;--chip-h:28px;--chip-f:16px;--deal:24px;--verb:104px;--size:36px}}
*{box-sizing:border-box}
html,body{margin:0;height:100%}
body{background:var(--ink);color:var(--white);font:400 14px/1.45 var(--body);min-width:544px;-webkit-font-smoothing:antialiased}
button{font:inherit;color:inherit;cursor:pointer}
:focus-visible{outline:2px solid var(--white);outline-offset:2px;box-shadow:0 0 0 2px var(--ink)}
.num{font-family:var(--display);font-weight:800;font-variant-numeric:tabular-nums lining-nums;line-height:1}
.eyebrow{font-size:11px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:var(--grey);line-height:1.2;white-space:nowrap}
.app{display:grid;grid-template-columns:minmax(0,1fr);grid-template-rows:auto auto auto auto auto;align-content:start;gap:var(--gap);min-height:100%;padding:0 var(--gut) 8px;max-width:640px;margin:0 auto}
/* top bar */
.header{display:grid;grid-template-columns:minmax(0,1fr) auto;grid-template-areas:"bar tools" "strip strip";align-items:center;column-gap:12px;margin:0 calc(-1*var(--gut));padding:0 var(--gut);border-bottom:1px solid var(--line)}
.bar{grid-area:bar;display:flex;align-items:center;gap:12px;height:48px}
.tools{grid-area:tools}.strip{grid-area:strip;border-top:1px solid var(--line);margin:0 calc(-1*var(--gut));padding:0 var(--gut)}
.brand{display:flex;align-items:center;gap:10px}
.brand svg{width:28px;height:28px;flex:none}
.word{display:none;font:italic 800 24px/1 var(--display);text-transform:uppercase;letter-spacing:-.01em}
.word b{color:var(--yellow);font-weight:800}
.tabs{display:flex;padding:2px;background:var(--panel);border:1px solid var(--line);border-radius:var(--r-pill)}
.tab{height:38px;padding:0 12px;border:0;background:none;border-radius:var(--r-pill);font-weight:600;font-size:13px;color:var(--grey);white-space:nowrap}
.tab[aria-selected=true]{background:var(--line);color:var(--white)}
.tools{margin-left:auto;display:flex;gap:4px}
.tool{width:44px;height:44px;border:0;background:none;border-radius:var(--r-ctl);color:var(--grey);display:grid;place-items:center}
.tool svg{width:20px;height:20px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
/* strip */
.strip{display:flex;align-items:center;gap:8px;height:52px}
.stat{display:flex;align-items:center;gap:6px}
.stat .v{font-size:20px}
.stat small{font:600 12px/1 var(--body);color:var(--soft)}
.step{width:44px;height:44px;flex:none;border:1px solid var(--line-strong);background:var(--ink);border-radius:var(--r-ctl);font:800 24px/1 var(--display);color:var(--white)}
.step.due{border-color:var(--yellow);color:var(--yellow)}
.pill{display:inline-flex;align-items:center;height:22px;padding:0 10px;border-radius:var(--r-pill);font-size:12px;font-weight:700;letter-spacing:.02em;text-transform:uppercase;background:var(--line);color:var(--soft);white-space:nowrap}
.pill.warn{background:none;box-shadow:inset 0 0 0 1px var(--white);color:var(--white)}
.pill.you{background:var(--white);color:var(--ink)}
.wideonly{display:none}
/* advice */
.advice{display:flex;flex-direction:column;gap:var(--gap)}
.slab{border-radius:var(--r-card);padding:12px 16px;background:var(--panel);border:1px solid var(--line-strong);display:flex;flex-direction:column;gap:4px}
.slab.go{background:var(--yellow);border-color:var(--yellow);color:var(--ink)}
.slab.go .eyebrow,.slab.go .sit{color:var(--ink)}
.slab.stay{border:2px solid var(--white)}
.slab .head{display:flex;justify-content:space-between;align-items:center}
.sure{display:flex;align-items:center;gap:6px}
.pips{display:flex;gap:3px}.pips i{width:6px;height:12px;border-radius:2px;border:1.5px solid currentColor}.pips i.on{background:currentColor}
.act{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap}
.verb{font:italic 800 var(--verb)/.9 var(--display);text-transform:uppercase;letter-spacing:-.01em}
.size{font:800 var(--size)/1 var(--display);text-transform:uppercase;font-variant-numeric:tabular-nums}
.sit{font-size:13px;font-weight:500;color:var(--soft);display:flex;align-items:center;gap:6px;flex-wrap:wrap}
.why{background:var(--panel);border:1px solid var(--line);border-radius:var(--r-card);padding:12px 14px;display:none;flex-direction:column;gap:10px}
.why p{margin:0;font-size:15px;color:var(--soft)}
.tiles{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
.tile{background:var(--ink);border:1px solid var(--line);border-radius:var(--r-tile);padding:12px 14px}
.tile .num{font-size:36px;margin-top:4px}
.tile .sub{font-size:12px;color:var(--grey);margin-top:2px}
.inline-key{display:flex;gap:8px;align-items:baseline;font-size:13px;color:var(--soft)}
.inline-key .num{font-size:20px;color:var(--white)}
.win{color:var(--win)}.loss{color:var(--loss)}
.chart{display:none;background:var(--panel);border:1px solid var(--line);border-radius:var(--r-card);padding:12px 14px;flex-direction:column;gap:8px}
.grid13{display:grid;grid-template-columns:repeat(13,minmax(0,1fr));gap:1px}
.cell{height:24px;display:grid;place-items:center;font:700 12px/1 var(--display);background:var(--ink);color:var(--grey);border-radius:3px}
.cell.in{background:var(--yellow);color:var(--ink)}
.cell.call{background:var(--white);color:var(--ink)}
.cell.mix{background:var(--yellow-tint);color:var(--yellow)}
.cell.me{box-shadow:0 0 0 2px var(--ink),0 0 0 4px var(--white);z-index:1;position:relative}
.legend{display:flex;gap:14px;font-size:12px;color:var(--soft);align-items:center}
.legend i{display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:6px;vertical-align:-1px}
/* table */
.table{position:relative;height:var(--table-h)}
.felt{position:absolute;left:calc(var(--pod-w)/2);right:calc(var(--pod-w)/2);top:calc(var(--pod-h)/2);bottom:calc(var(--hero-h)/2);background:var(--panel);border:1px solid var(--line);border-radius:var(--r-pill)}
.pod{position:absolute;width:var(--pod-w);height:var(--pod-h);background:var(--ink);border:1px solid var(--line-strong);border-radius:var(--r-tile);padding:7px 9px;display:flex;flex-direction:column;justify-content:space-between;text-align:left}
.pod .top{display:flex;justify-content:space-between;align-items:center;gap:4px}
.pos{font:800 var(--pos)/1 var(--display);text-transform:uppercase;letter-spacing:.01em}
.key{min-width:18px;height:18px;padding:0 4px;display:grid;place-items:center;border:1px solid var(--line-strong);border-radius:5px;font:700 11px/1 var(--body);color:var(--grey)}
.stack{display:flex;align-items:baseline;gap:3px}
.stack .num{font-size:var(--stack)}
.stack u{text-decoration:none;font:700 11px/1 var(--body);color:var(--grey)}
.stack .chips,.pod .name{display:none;font:500 12px/1.2 var(--body);color:var(--grey);margin-left:auto}
.pod .name{margin:0;color:var(--soft);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.pod.folded{border-color:var(--line);color:var(--grey)}
.pod.folded .num{color:var(--grey)}
.pod.target{border:2px solid var(--white);padding:6px 8px}
.pod.turn{border:2px solid var(--yellow);padding:6px 8px;background:#1E1A0B}
.pod.turn .pos{color:var(--yellow)}
.pod.away{border-style:dashed;color:var(--grey)}
.pod.away .num{color:var(--grey)}
.pod.empty{border:1px dashed var(--grey);background:none;display:grid;place-items:center;color:var(--grey);font-weight:600;font-size:13px}
.pod.allin .stack .num{font-style:italic}
.pod.hero{width:var(--hero-w);height:var(--hero-h);flex-direction:row;gap:8px;align-items:center;justify-content:flex-start;padding:5px 7px}
.pod.hero .info{display:flex;flex-direction:column;justify-content:space-between;align-self:stretch;flex:1;min-width:0;padding:2px 0}
.hand{display:flex;gap:4px}
.chip{position:absolute;height:var(--chip-h);min-width:40px;padding:0 8px;display:grid;place-items:center;border-radius:var(--r-pill);background:var(--line);color:var(--white);font:800 var(--chip-f)/1 var(--display);font-variant-numeric:tabular-nums;white-space:nowrap}
.chip.allin{background:var(--white);color:var(--ink)}
.deal{position:absolute;width:var(--deal);height:var(--deal);border-radius:50%;background:var(--white);color:var(--ink);display:grid;place-items:center;font:800 calc(var(--deal)*.62)/1 var(--display);box-shadow:0 0 0 2px var(--ink);z-index:2}
.centre{position:absolute;left:50%;top:46%;transform:translate(-50%,-50%);display:flex;flex-direction:column;align-items:center;gap:6px}
.pot{display:flex;align-items:baseline;gap:8px;height:26px}
.pot .num{font-size:24px}
.pot small{font-size:12px;color:var(--grey)}
.board{display:flex;gap:8px}.board .street{display:flex;gap:4px}
.card{width:var(--card-w);height:var(--card-h);background:var(--white);color:var(--ink);border-radius:calc(var(--card-w)*.13);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:1px;flex:none}
.card b{font:800 calc(var(--card-h)*.5)/.9 var(--display);letter-spacing:-.02em}
.card svg{width:calc(var(--card-h)*.3);height:calc(var(--card-h)*.3);fill:currentColor;stroke:currentColor;stroke-width:0;stroke-linejoin:round}
.card svg.open,.txt svg.open{fill:none;stroke-width:2.4}
.card.h{width:var(--hcard-w);height:var(--hcard-h)}
.card.h b{font-size:calc(var(--hcard-h)*.5)}.card.h svg{width:calc(var(--hcard-h)*.3);height:calc(var(--hcard-h)*.3)}
.card.slot{background:none;border:1.5px dashed var(--line-strong)}
.card.slot.cur{border:2px solid var(--white)}
.four .card .hh{color:#B3121A}.four .card .dd{color:#1D4ED8}.four .card .cc{color:#0B6B32}
.txt svg{width:.8em;height:.8em;fill:currentColor;stroke:currentColor;stroke-width:0;vertical-align:-.06em;margin-left:1px}
/* hand line */
.line{display:flex;gap:6px;align-items:center;height:36px;overflow:hidden}
.ev{flex:none;height:28px;padding:0 10px;display:inline-flex;align-items:center;gap:4px;border-radius:var(--r-pill);background:var(--panel);border:1px solid var(--line);font-size:13px;font-weight:600;color:var(--soft);white-space:nowrap}
.ev b{font:800 15px/1 var(--display);color:var(--white);font-variant-numeric:tabular-nums}
.ev.sel{border-color:var(--white);color:var(--white)}
/* action bar */
.actions{display:flex;gap:6px;align-items:stretch;align-self:start}
.line{align-self:start}
.btn{min-height:48px;min-width:0;padding:0 8px;border-radius:var(--r-btn);border:1px solid var(--line-strong);background:var(--ink);color:var(--white);font:800 16px/1 var(--display);text-transform:uppercase;letter-spacing:.02em;display:inline-flex;align-items:center;justify-content:center;gap:6px;white-space:nowrap;flex:1}
.btn kbd{font:700 11px/1 var(--body);min-width:18px;height:18px;padding:0 4px;display:grid;place-items:center;border:1px solid var(--line-strong);border-radius:5px;color:var(--grey);letter-spacing:0}
.btn.primary{background:var(--yellow);border-color:var(--yellow);color:var(--ink);flex:1.8}
.btn.primary kbd{border-color:var(--ink);color:var(--ink)}
@media (min-width:1024px){
  .app{max-width:none;grid-template-columns:minmax(0,1fr) 360px;grid-template-rows:auto auto auto auto;column-gap:16px}
  .header{grid-column:1/-1}.bar{height:52px}
  .word{display:block}.brand svg{width:32px;height:32px}
  .advice{grid-column:2;grid-row:2/5}
  .table,.line,.actions{grid-column:1}
  .why{display:flex}
  .btn{font-size:18px;gap:8px;padding:0 14px}.actions{gap:8px}
  .inline-key{display:none}
  .slab{padding:16px 20px}
  .act{flex-direction:column;gap:4px}
  .stack .chips{display:block}
}
@media (min-width:1280px){
  .app{grid-template-columns:minmax(0,1fr) 440px;column-gap:24px}
  .header{grid-template-columns:auto minmax(0,1fr) auto;grid-template-areas:"bar strip tools";column-gap:24px}
  .bar{height:64px;gap:20px}.brand svg{width:36px;height:36px}
  .strip{border-top:0;margin:0;padding:0;height:64px;gap:12px}
  .wideonly{display:flex}
  .chart{display:flex}
  .slab{padding:20px 24px}
  .pod{padding:9px 12px}.pod.target,.pod.turn{padding:8px 11px}
  .pod .name{display:block}
  .pod.hero{padding:7px 9px;gap:12px}
  .pot{height:36px}.pot .num{font-size:32px}
  .stat .v{font-size:24px}
}
"""

MARK = '<svg viewBox="0 0 40 40" role="img" aria-label="Menlo Bet"><rect width="40" height="40" rx="9" fill="#FFD60A"/><path d="M8 30V11l12 11 12-11v19h-5V22l-7 6.5L13 22v8z" fill="#0A0A0B"/></svg>'


def suit(s, cls=''):
    open_ = ' open' if s in 'hd' else ''
    return '<svg class="%s%s %s"><use href="#%s"/></svg>' % (s + s, open_, cls, s)


def card(code, hero=False):
    r, s = code[0], code[1]
    r = '10' if r == 'T' else r
    return '<span class="card%s"><b class="%s">%s</b>%s</span>' % (' h' if hero else '', s + s, r, suit(s))


def pod_style(side, pos, hero=False):
    w, h = ('var(--hero-w)', 'var(--hero-h)') if hero else ('var(--pod-w)', 'var(--pod-h)')
    if side == 'T':
        return 'top:0;left:calc(%d%% - %s/2)' % (pos, w)
    if side == 'B':
        return 'bottom:0;left:calc(%d%% - %s/2)' % (pos, w)
    if side == 'L':
        return 'left:0;top:calc(%d%% - %s/2)' % (pos, h)
    return 'right:0;top:calc(%d%% - %s/2)' % (pos, h)


def chip_style(side, pos, hero=False):
    w, h = ('var(--hero-w)', 'var(--hero-h)') if hero else ('var(--pod-w)', 'var(--pod-h)')
    if side == 'T':
        return 'top:calc(%s + 6px);left:%d%%;transform:translateX(-50%%)' % (h, pos)
    if side == 'B':
        return 'bottom:calc(%s + 6px);left:%d%%;transform:translateX(-50%%)' % (h, pos)
    if side == 'L':
        return 'left:calc(%s + 6px);top:%d%%;transform:translateY(-50%%)' % (w, pos)
    return 'right:calc(%s + 6px);top:%d%%;transform:translateY(-50%%)' % (w, pos)


def deal_style(side, pos, hero=False):
    w, h = ('var(--hero-w)', 'var(--hero-h)') if hero else ('var(--pod-w)', 'var(--pod-h)')
    d = 'var(--deal)'
    if side in 'TB':
        right = pos <= 50
        x = 'calc(%d%% %s %s/2 - %s/2)' % (pos, '+' if right else '-', w, d)
        y = ('top:calc(%s - %s/2)' % (h, d)) if side == 'T' else ('bottom:calc(%s - %s/2)' % (h, d))
        return 'left:%s;%s' % (x, y)
    below = pos < 46
    y = 'calc(%d%% %s %s/2 - %s/2)' % (pos, '+' if below else '-', h, d)
    x = ('left:calc(%s - %s/2)' % (w, d)) if side == 'L' else ('right:calc(%s - %s/2)' % (w, d))
    return 'top:%s;%s' % (y, x)


def build(fonts, mode='tournament', n=9):
    slots = SLOTS[n]
    names = ORDER[n]
    # button seat: so that hero is the CO where possible
    seats = []
    btn = {9: 1, 8: 1, 7: 1, 6: 1, 5: 1, 4: 1, 3: 0, 2: 0}[n]
    # preflop order starts left of the button: seat btn+1 = SB ... ; label by distance
    labels = {}
    for k in range(n):
        seat = (btn + 1 + k) % n          # SB first
        labels[seat] = (['SB', 'BB'] + names[:-2])[k] if n > 2 else ['BB', 'BTN/SB'][k]
    demo = {
        9: [('hero', '21.5', '12,900', ''), ('', '34.0', '20,400', 'Ann'), ('', '18.2', '10,920', 'Carl'),
            ('', '52.1', '31,260', 'Dee'), ('folded', '9.4', '5,640', 'Gus'), ('folded', '27.0', '16,200', 'Fox'),
            ('raise', '40.3', '24,180', 'Hal'), ('folded', '15.8', '9,480', 'Ivo'), ('away', '12.0', '7,200', 'Jo')],
    }
    rows = demo.get(n) or [('hero', '8.0', '', '')] + [('', '8.0', '', '')] * (n - 1)
    out = []
    for i, (side, pos) in enumerate(slots):
        st, bb, chips, name = rows[i]
        hero = i == 0
        cls = 'pod'
        if hero: cls += ' hero turn'
        if st == 'folded': cls += ' folded'
        if st == 'away': cls += ' away'
        if st == 'raise': cls += ''
        key = '<span class="pill you">You</span>' if hero else '<span class="key">%d</span>' % (i + 1)
        inner = ('<div class="top"><span class="pos">%s</span>%s</div>'
                 '<div class="stack"><span class="num">%s</span><u>bb</u><span class="chips">%s</span></div>' % (labels[i], key, bb, chips))
        if hero:
            inner = '<div class="hand">%s%s</div><div class="info">%s</div>' % (card('Ah', True), card('Kd', True), inner)
        elif name and st != 'away':
            inner += '<div class="name">%s</div>' % name
        elif st == 'away':
            inner += '<div class="name">Away</div>'
        out.append('<button class="%s" style="%s">%s</button>' % (cls, pod_style(side, pos, hero), inner))
        if labels[i] == 'SB':
            out.append('<span class="chip" style="%s">0.5bb</span>' % chip_style(side, pos, hero))
        if labels[i] == 'BB':
            out.append('<span class="chip" style="%s">1bb</span>' % chip_style(side, pos, hero))
        if st == 'raise':
            out.append('<span class="chip" style="%s">2.2bb</span>' % chip_style(side, pos, hero))
        if i == btn:
            out.append('<span class="deal" style="%s">D</span>' % deal_style(side, pos, hero))
    board = ('<div class="board"><div class="street">%s%s%s</div><div class="street">%s</div><div class="street">%s</div></div>'
             % (card('Ks'), card('7d'), card('2c'), card('Th'), '<span class="card slot cur"></span>'))
    table = '<div class="table"><div class="felt"></div>%s<div class="centre"><div class="pot"><span class="eyebrow">Pot</span><span class="num">4,500</span><small>7.5bb</small></div>%s</div></div>' % (''.join(out), board)

    grid = []
    R = 'AKQJT98765432'
    for r in range(13):
        for c in range(13):
            h = R[r] + R[c] if r == c else (R[r] + R[c] + 's' if r < c else R[c] + R[r] + 'o')
            cls = 'cell'
            if r == c and r <= 9: cls += ' in'
            elif r < c and (r == 0 or (r <= 2 and c <= 5) or (r == c - 1 and r < 8)): cls += ' in'
            elif r > c and c == 0 and r <= 5: cls += ' in'
            elif r > c and c == 1 and r <= 3: cls += ' in'
            elif (r < c and r <= 3 and c <= 7) or (r > c and c == 0 and r <= 7): cls += ' mix'
            elif r < c and r <= 5 and c <= 8: cls += ' call'
            if h == 'AKo': cls += ' me'
            grid.append('<span class="%s">%s</span>' % (cls, h))

    html = '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Menlo Coach</title><style>%s</style></head><body>%s
<div class="app">
<header class="header"><div class="bar"><div class="brand">%s<span class="word">Menlo<b>.bet</b></span></div>
<div class="tabs" role="tablist"><button class="tab" role="tab" aria-selected="true">Tournament</button><button class="tab" role="tab">Spin &amp; Go</button><button class="tab" role="tab">All-In or Fold</button></div></div>
<div class="tools"><button class="tool" aria-label="Undo"><svg viewBox="0 0 24 24"><path d="M9 14 4 9l5-5"/><path d="M4 9h10a6 6 0 0 1 0 12h-3"/></svg></button><button class="tool" aria-label="Menu"><svg viewBox="0 0 24 24"><path d="M4 7h16M4 12h16M4 17h16"/></svg></button></div>
<div class="strip">
<div class="stat"><button class="step" aria-label="Blinds down">&minus;</button><div><div class="eyebrow">Level 12</div><div><span class="num v">300 / 600</span> <small>ante 75</small></div></div><button class="step due" aria-label="Blinds up">+</button></div>
<div class="stat"><button class="step" aria-label="One fewer player">&minus;</button><div><div class="eyebrow">Left</div><div class="num v">96</div></div><button class="step" aria-label="One more player">+</button></div>
<div class="stat"><div><div class="eyebrow">Paid</div><div class="num v">75</div></div></div>
<span class="pill warn">21 from the money</span>
<div class="stat wideonly"><div><div class="eyebrow">Average</div><div class="num v">52.1k</div></div></div>
</div></header>
<section class="advice" aria-live="polite">
<div class="slab go"><div class="head"><span class="eyebrow">Coach</span><span class="sure eyebrow"><span class="pips"><i class="on"></i><i class="on"></i><i></i></span>Standard</span></div>
<div class="act"><span class="verb">Raise</span><span class="size">to 2.2bb &middot; 1,320</span></div>
<div class="sit"><span class="txt">A%sK%s</span> in the cutoff, 21.5bb, folded to you</div></div>
<div class="inline-key"><span>Steal works when the blinds fold 62%% of the time.</span></div>
<div class="why"><p>The blinds are tight and you cover both. A raise keeps the fold option against an all-in.</p>
<div class="tiles"><div class="tile"><div class="eyebrow">Open range here</div><div class="num">26%%</div><div class="sub">A9o+ is inside it</div></div>
<div class="tile"><div class="eyebrow">Fold to an all-in</div><div class="num loss">&minus;2.2bb</div><div class="sub">unless TT+, AQ+</div></div></div>
<div class="eyebrow">Also fine</div><p style="font-size:13px">All-in is close behind: +0.31bb.</p></div>
<div class="chart"><div class="head" style="display:flex;justify-content:space-between"><span class="eyebrow">Cutoff, first in, 21.5bb</span><span class="eyebrow">26%% of hands</span></div><div class="grid13">%s</div>
<div class="legend"><span><i style="background:#FFD60A"></i>Raise</span><span><i style="background:#FFFFFF"></i>Call</span><span><i style="background:#3F3815"></i>Close</span><span><i style="background:#0A0A0B;box-shadow:inset 0 0 0 1px #3A3A42"></i>Fold</span></div></div>
</section>
%s
<div class="line"><span class="ev"><b class="txt">A%sK%s</b></span><span class="ev">Hal <b>raise 2.2</b></span><span class="ev sel">You <b>call</b></span><span class="ev"><b class="txt">K%s7%s2%s</b></span><span class="ev">Hal <b>bet 1,500</b></span></div>
<div class="actions"><button class="btn primary">Follow <kbd>Space</kbd></button><button class="btn">Fold <kbd>F</kbd></button><button class="btn">Call <kbd>C</kbd></button><button class="btn">Raise <kbd>R</kbd></button><button class="btn">All-in <kbd>A</kbd></button></div>
</div></body></html>''' % (CSS.replace('FONTS', fonts), SUITS, MARK, suit('h'), suit('d'), ''.join(grid), table,
                           suit('h'), suit('d'), suit('s'), suit('d'), suit('c'))
    return html


if __name__ == '__main__':
    fonts, out = sys.argv[1], sys.argv[2]
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 9
    open(out, 'w').write(build(fonts, n=n))
