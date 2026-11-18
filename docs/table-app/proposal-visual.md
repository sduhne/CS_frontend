# Proposal: visual design, brand and layout

Lens: how the table coach looks in the menlo.bet brand at 1440, 1024 and 560 px. Keys and rules belong to the other proposals. Every size below was rendered in a static mock with the bundled fonts.

## 1. Five rules

1. **Yellow means "do this now"**: the coach's answer and its range cells, the one button that carries it out (Follow, or Next hand), hero's seat while the decision is his. Two alerts borrow it: a blind level that is due, and the bubble.
2. **A white ring means "your next key lands here"**: keyboard focus, the seat being recorded, the active card slot.
3. **Green and red appear only on chips or big blinds won or lost**: EV, stack changes after a hand, session net, the IN THE MONEY pill.
4. **Brightness carries state, never opacity**: live seats white, folded seats grey, so contrast never drops.
5. **Four neutrals, no new ones**: Ink, Panel, Line, Line strong. No gradients, no blurred shadows, no emoji.

## 2. Tokens

```css
:root{
  --ink:#0A0A0B; --panel:#151518; --line:#26262B; --line-strong:#3A3A42;
  --yellow:#FFD60A; --yellow-hover:#E6B800;
  --yellow-wash:rgba(255,214,10,.08);  /* hero's turn: #1E1A0B on Ink */
  --yellow-tint:rgba(255,214,10,.18);  /* close cell: #3F3815 on Panel */
  --white:#FFFFFF; --soft:#C9C9D1; --grey:#9A9AA3;
  --win:#3DDC84; --loss:#FF5C5C;
  --win-tint:rgba(61,220,132,.18); --loss-tint:rgba(255,92,92,.18);
  --display:"Barlow Semi Condensed","MB Display Fallback",Arial,sans-serif;
  --body:Inter,"MB Body Fallback",system-ui,"Segoe UI",Arial,sans-serif;
  --r-card:16px; --r-tile:14px; --r-btn:14px; --r-ctl:12px; --r-in:10px; --r-pill:999px;
}
.num{font-family:var(--display);font-weight:800;line-height:1;
     font-variant-numeric:tabular-nums lining-nums}
.eyebrow{font:700 11px/1.2 var(--body);letter-spacing:.12em;text-transform:uppercase;color:var(--grey)}
:focus-visible{outline:2px solid var(--white);outline-offset:2px;box-shadow:0 0 0 2px var(--ink)}
```

Sizes that change with width (CSS variables switched by two media queries):

| Variable | under 1024 | 1024 to 1279 | 1280 and up |
|---|---|---|---|
| Page gutter, gap | 16, 8 | 16, 12 | 24, 16 |
| Advice column | full width | 360 | 440 |
| Table box height (All-In or Fold) | 304 (240) | 360 (300) | 460 (380) |
| Seat pod; hero pod | 100×56; 184×68 | 112×60; 216×80 | 152×80; 280×104 |
| Position name; stack | 18; 17 | 20; 18 | 26; 22 |
| Board card; hero card | 36×50; 40×56 | 44×62; 48×66 | 56×78; 64×88 |
| Bet chip height, type; dealer button | 22, 13; 18 | 24, 14; 20 | 28, 16; 24 |
| Advice verb; size line | 64; 28 | 88; 32 | 104; 36 |

`body{min-width:544px}`. Under 1024 the single column is capped at 640 px and centred.

## 3. Fonts

Seven latin woff2 files, 168 KB together, in `poker_coach/app/static/fonts/` with both OFL texts (already in `tableapp/fonts/pick/`): Barlow Semi Condensed 700, 800, 800 italic; Inter 400, 500, 600, 700. The subset covers Portuguese and Spanish accents. `font-display:swap`; preload Barlow 800, 800 italic, Inter 400 and 600.

Fallbacks measured from the font tables against Arial, so nothing moves when the real face arrives:

```css
@font-face{font-family:"MB Display Fallback";font-weight:700 800;
  src:local("Arial Bold"),local("Arial-BoldMT"),local("Liberation Sans Bold");
  size-adjust:83%;ascent-override:120.5%;descent-override:24.1%;line-gap-override:0%}
@font-face{font-family:"MB Display Fallback";font-weight:800;font-style:italic;
  src:local("Arial Bold Italic"),local("Arial-BoldItalicMT"),local("Liberation Sans Bold Italic");
  size-adjust:77%;ascent-override:130%;descent-override:26%;line-gap-override:0%}
@font-face{font-family:"MB Body Fallback";
  src:local("Arial"),local("ArialMT"),local("Liberation Sans");
  size-adjust:107.5%;ascent-override:90.1%;descent-override:22.4%;line-gap-override:0%}
```

Found in the files:

- Both faces have `tnum`, but figures are proportional by default (Barlow's 1 is 325 units, its 0 is 514). Without `tabular-nums` every stack jitters.
- Neither subset has the suit characters and Barlow has no arrows: suits and chevrons are inline SVG. U+2212 exists in both: use it for minus.
- Never write `font-family: Menlo`: on a Mac that is Apple's monospace face.

## 4. Layout

One DOM order at every width: header, advice (`aria-live="polite"`), table, hand line, action bar. From 1024 grid places the advice in the right column.

**1440** (`grid-template-columns: minmax(0,1fr) 440px`)

```
┌────────────────────────────────────────────────────────────────────────────────┐
│ [M] MENLO.BET (tabs) [−] L12 300/600 a75 [+] [−] 96 [+] PAID 75 (STAGE) AVG ↶ ≡│ 64
├─────────────────────────────────────────────┬──────────────────────────────────┤
│ TABLE 928×460                               │ SLAB  COACH         ▮▮▯ STANDARD │
│ pods on the rail, pot and board             │ RAISE                            │
│ at the centre, hero pod bottom centre       │ TO 2.2BB · 1,320                 │
│ with his two cards inside it                │ A♡K♢ in the cutoff, folded to you│
├─────────────────────────────────────────────┤ WHY  one reason, two number tiles│
│ HAND LINE 36                                │ RANGE  13×13, cells 31×24        │
│ ACTION BAR 48                               │ (tabs Why | Range under 880 high)│
└─────────────────────────────────────────────┴──────────────────────────────────┘
```

**1024** (`minmax(0,1fr) 360px`)

```
┌──────────────────────────────────────────────────────────┐
│ [M] MENLO.BET (tabs)                                 ↶ ≡ │ 52
│ [−] L12 300/600 a75 [+] [−] 96 [+] PAID 75 (STAGE)       │ 52
├───────────────────────────────────┬──────────────────────┤
│ TABLE 616×360                     │ SLAB, verb 88        │
│ HAND LINE 36, ACTION BAR 48       │ tabs: Why | Range    │
└───────────────────────────────────┴──────────────────────┘
```

**560**, single column; everything shown fits 560×720

```
┌────────────────────────────────────────────────────────┐
│ [M] (Tournament | Spin & Go | All-In or Fold)     ↶  ≡ │ 48
│ [−] L12 300/600 a75 [+] [−] 96 [+] PAID 75 (21 FROM…)  │ 52
│ COACH                                    ▮▮▯ STANDARD  │
│ RAISE  TO 2.2BB · 1,320                                │ slab 126
│ A♡K♢ in the cutoff, 21.5bb, folded to you              │
│ Steal works when the blinds fold 62%.   Why and range ›│ 44
│          [UTG 9.4]        [UTG+1 27.0]                 │
│ [BB 52.1] 1bb     POT 4,500      2.2bb [UTG+2 40.3]    │ table 304
│ [SB 18.2] 0.5bb   K♠ 7♢ 2♣ 10♡ [ ]     [LJ 15.8]       │
│ [BTN 34.0]ᴰ   [A♡ K♢  CO  YOU 21.5]    [HJ away]       │
│ (A♡K♢)(Hal raise 2.2)(You call)(K♠7♢2♣)(Hal bet 1,500) │ 36
│ [FOLLOW Space] [FOLD F] [CALL C] [RAISE R] [ALL-IN A]  │ 48
└────────────────────────────────────────────────────────┘
```

What collapses at 560: the wordmark (the mark stays); average stack, goal and entrants move to the menu; the size joins the verb's row; Why becomes one line, and that line is the button that opens the full reasons and the range chart as a sheet over the table; pods drop the name and the second unit; the hand line scrolls sideways. Only the full Why panel sits below the fold.

**Modes** (same frame at every width; only these regions change)

```
Spin & Go                                     All-In or Fold
[−] L3 20/40 [+] (Solid|Loose) 12 GAMES 5 WON 8BB CAP (Solid|Loose|Very loose) NET +3.4bb
   [SB 12.0] 0.5bb      1bb [BB 9.5]                    [BTN 8.0]
            POT 60                            [CO ALL-IN] 8bb  POT 9.5bb  [SB 8.0]
       [K♠ 7♢ BTNᴰ YOU 8.5]                         [A♠ 5♠ BB YOU 8.0]
[FOLLOW][ALL-IN A][FOLD F][CALL C]            [FOLLOW Space]  [ALL-IN A]  [FOLD F]
```

| | Tournament | Spin & Go | All-In or Fold |
|---|---|---|---|
| Strip | level, blinds −/+, players left −/+, paid, stage pill; from 1280 average and goal | level, blinds −/+, opponents, games and wins | fixed blinds, opponents, session net (green or red) |
| Table | 2 to 9 pods | 3 pods; 2 heads-up | 4 pods, big blinds only, shorter box |
| Centre | pot, board | pot; board only on a free flop | pot |
| Key tile | EV, equity or range share | the same | "+0.12bb against folding"; under 0.05bb a COIN FLIP pill |

**Seat slots.** Hero first, then clockwise. The letter is the edge the pod sits flush against (bottom, left, top, right); the number is its centre along that edge in percent.

| Seats | Slots |
|---|---|
| 2, 3 | B50 T50; B50 T25 T75 |
| 4, 5 | B50 L46 T50 R46; B50 L58 T28 T72 R58 |
| 6 | B50 L66 L34 T50 R34 R66 |
| 7 | B50 L66 L35 T35 T65 R35 R66 |
| 8 | B50 B11 L52 T22 T50 T78 R52 B89 |
| 9 | B50 B11 L60 L34 T35 T65 R34 R60 B89 |

## 5. Components

| Component | Specification |
|---|---|
| Header | 1px Line below. Mark 36/32/28. Wordmark Barlow 800 italic 24, uppercase, −.01em, ".BET" yellow |
| Mode tabs | Track: Panel, 1px Line, pill, padding 2. Tab: 40 high, padding 0 12, Inter 600 13, Grey. Selected: Line fill, White. Hover: White |
| Strip value | Eyebrow above a `.num` 20 (24 from 1280); "ante 75" Inter 600 12 Soft. A click turns the value into an input |
| Stepper | 44×44, Ink, 1px Line strong, radius 12, "−" or "+" Barlow 800 24. Hover: White border. Pressed: Line fill. Level due: yellow border and glyph |
| Pill | 22 high, padding 0 10, Inter 700 12 uppercase. Neutral: Line with Soft. Near the money: 1px White outline, White text. Bubble: yellow fill, Ink. In the money: win tint, Win. YOU: White fill, Ink |
| Felt | Inset half a pod from each edge of the table box. Panel, 1px Line, radius 999 |
| Seat pod | A `<button>`. Ink, 1px Line strong, radius 14, padding 7 9 (9 12 from 1280). Row 1: position name Barlow 800 uppercase, and an 18×18 keycap (Inter 700 11 Grey, 1px Line strong, radius 5). Row 2: stack `.num`, "bb" Inter 700 11 Grey; from 1024 the chips, Inter 500 12 Grey. Row 3 from 1280: name, Inter 500 12 Soft |
| Hero pod | His two cards, then position, YOU pill and stack. His turn: 2px yellow border, yellow wash, position name yellow |
| Pod states | Target: 2px White border. Folded: 1px Line, all text Grey. All-in: the stack reads ALL-IN in italic and the bet chip turns White with Ink text. Away: dashed border, Grey text, "Away". Empty: 1px dashed Grey, "+ Seat". Unsure stack: "~" before it, Grey. After a result: "+3,200" Win or "−1,500" Loss for two seconds |
| Bet chip | Pill 6px outside the pod on the felt side. Line fill, White `.num`, padding 0 8 |
| Dealer button | White circle, Ink "D", 2px Ink halo, centred on the pod corner nearest the table centre. It can be dragged |
| Pot and board | Centred at 50% across, 46% down. "POT" eyebrow, `.num` 24 (32 from 1280), other unit Inter 12 Grey. Board 6px below: 4px between flop cards, 8px between streets |
| Hand line | Chips 28 high, Panel, 1px Line, pill, Inter 600 13 Soft with the action in `.num` 15 White. Selected: White border. Pointer area 44 high |
| Primary button | Yellow, Ink text, Barlow 800 18 uppercase (16 under 1024), .02em, min-height 48, radius 14. Hover #E6B800. Disabled: Line fill, Grey text |
| Secondary button | Ink, 1px Line strong, White text. Hover: White border. Pressed: Line fill. The keycap sits inside the button |
| Action bar | One row. Follow takes 1.8 shares, the others 1. Bet or Raise swaps the hand line for an amount input and preset pills, so nothing jumps |
| Input | 44 high, Ink, 1px Grey, radius 10, `.num` 20. Focus: White border and ring |
| Number tile | Ink, 1px Line, radius 14, padding 12 14. Eyebrow, `.num` 36, note Inter 12 Grey |
| Menu, sheet, toast | Panel, 1px Line strong, radius 14, a 4px solid Ink halo, no shadow. Rows 44 high |

## 6. Cards and suits

**One-ink deck.** White faces, Ink ranks in Barlow 800 at half the card's height ("10", not "T"), the suit below at 30% of the height. Radius 13% of the width. Spades and clubs are solid; hearts and diamonds are outlines (stroke 2.4 in a 24 box). Empty slot: 1.5px dashed Line strong; active slot: 2px White.

Why:

- It is the long-standing convention for card diagrams printed in one ink, and Unicode's first four suit characters are exactly these: ♠ ♡ ♢ ♣.
- It needs no hue, so red stays "loss", yellow stays "do this", and nothing depends on colour vision.
- It inverts cleanly: the same glyphs are white on the dark hand line. In the mock they read at 36×50 and inside 13 px text.
- White card faces are the only large white areas, so the eye finds the cards first.

**Option, off by default: four-colour deck.** Spades Ink, hearts #B3121A, diamonds #1D4ED8, clubs #0B6B32, all solid, for players whose client uses one. It is the single exception to the palette: these inks appear only inside a white card, and the hand line keeps the one-ink glyphs. Drop it if the brand must stay pure.

Picking a card with the pointer is two steps that mirror the keys, rank then suit, with every target at least 44 px.

## 7. The recommended action

The verb alone is the headline: Barlow 800 italic, uppercase, line-height .9. The size ("TO 2.2BB · 1,320") is the second line. Qualifiers ("and call any all-in", "semi-bluff") become a pill under it.

| Answer | Slab | Text |
|---|---|---|
| RAISE, BET, 3-BET, 4-BET, ALL-IN | yellow fill | Ink |
| CALL, CHECK | Panel, 2px White border | White |
| FOLD | Panel, 1px Line strong | White |
| WAIT, NO ADVICE, no cards yet | Ink, 1px dashed Grey, verb 48 | Grey |
| Updating | the dashed slab, eyebrow UPDATING, Follow disabled | Grey |

Three brightness levels map to aggression and do not depend on colour vision; an out-of-date answer never wears yellow. How sure: three 6×12 bars in the text colour (three filled is clear, two standard, one close) and the word. A close answer prints the alternative under "ALSO FINE". Slab radius 16; padding 20 24, 16 20 or 12 16 by width.

**Range chart.** 13×13, 1px gaps, cells 24 high, labels Barlow 700 12. Raise or all-in: yellow, Ink text. Call: White, Ink text. Close or mixed: yellow tint, yellow text. Fold: Ink, Grey text. Hero's hand: a 2px Ink ring inside a 2px White ring. A legend with the share of hands sits below.

## 8. Contrast

| Text | on Ink | on Panel | on Line | Elsewhere |
|---|---|---|---|---|
| White | 19.8 | 18.2 | 15.1 | Line strong 11.3; hero's turn wash 17.4 |
| Soft | 12.0 | 11.1 | 9.2 | |
| Grey | 7.1 | 6.5 | 5.4 | wash 6.2; Line strong 4.0, so never |
| Yellow | 14.0 | 12.9 | 10.7 | wash 12.3; close cell 8.3 |
| Win | 11.1 | 10.2 | | its tint pill 7.1 |
| Loss | 6.5 | 6.0 | | its tint pill 4.7 |
| Ink | | | | Yellow 14.0; Yellow hover 10.6; White 19.8 |
| Four-colour inks | | | | White 6.6 to 7.0 |

Line and Line strong are 1.3 and 1.8 against Ink: decoration only. Anything whose edge must be seen (inputs, empty seats) uses a Grey border. Grey on White is 2.8 and Yellow on White 1.4: never.

## 9. Focus, targets, motion, words

**Tab order:** skip link, mode tabs (one stop, arrows inside), blinds − value +, players left − value +, paid, undo, menu, Why and Range tabs, table (one stop; arrows go round the seats clockwise from hero, then the board), hand line (one stop), action bar from Follow to All-in. The speed proposal binds Tab to "next opponent"; I recommend leaving Tab to the browser.

**Targets:** every control is at least 44×44. The flop is one target, hero's two cards are one, and the turn and river each borrow 4px of gap on both sides. Smaller, with other routes: chart cells (24 high) and the dealer button (seat menu, keys).

**Motion:** 120 ms on borders and fills; the verb changes with no animation; the due-level `+` blinks once a second. Under `prefers-reduced-motion` nothing moves.

| Place | Words |
|---|---|
| Eyebrows | COACH · YOUR TURN · LEVEL 12 · LEFT · PAID · POT · TO CALL · ALSO FINE · WATCH OUT |
| How sure | Clear · Standard · Close |
| Stage | EARLY · MIDDLE · 21 FROM THE MONEY · BUBBLE · IN THE MONEY · FINAL TABLE |
| Buttons | Follow · Fold · Check · Call 600 · Bet · Raise · All-in · Next hand · Undo |
| No hand | NEW HAND. "Press N, then type your two cards: A K S." |
| Waiting | WAIT. "The cutoff has not acted yet." |
| Fold clock | "You can fold into the money." · "The blinds reach you first. Find an all-in." |
| Menu, once | "For study and play money. Real-money sites ban real-time help." |

## 10. Checked, and not

Files: `/tmp/claude-0/-home-user-CS-frontend/aa601cb2-5545-5621-9e0c-8faa1c3fd22d/scratchpad/visual-work/`.

- `mock.py`, `shot-*.png`: rendered in headless Chrome at 560×720, 1024×700 and 1440×1000 with nine, four and three seats.
- `seats.py`: for 2 to 9 seats at the three sizes no pod, bet chip, dealer button, pot or board overlaps (24 layouts, plus the three All-In or Fold boxes).
- `contrast.py` produced section 8; `metrics.py` read the font tables for section 3.
- Not drawn: sheets, menus, and the target, all-in and result seat states. Not checked: Windows rendering.
