/* Development only: saved examples of the view and the advice, and a switcher between them.

     index.html?fixture=list            every example, as links
     index.html?fixture=preflop-open    one example
     add &chrome=0 to hide the switcher (screenshots), &button=3 to move the dealer button
     in the seats-N examples, &unit=bb or &deck=four-colour to change any example.

   Nothing here is loaded in normal use: app.js adds this file only when the address has ?fixture=.
   The page is live: menus open and close, and an intent is shown in a toast instead of being sent. */
(function () {
  "use strict";

  /* ---------- Builders ---------- */

  // Seat names by the number of players dealt in, in the order they act before the flop.
  const ORDER = {
    2: ["BTN/SB", "BB"], 3: ["BTN", "SB", "BB"], 4: ["CO", "BTN", "SB", "BB"],
    5: ["HJ", "CO", "BTN", "SB", "BB"], 6: ["LJ", "HJ", "CO", "BTN", "SB", "BB"],
    7: ["UTG", "LJ", "HJ", "CO", "BTN", "SB", "BB"],
    8: ["UTG", "UTG+1", "LJ", "HJ", "CO", "BTN", "SB", "BB"],
    9: ["UTG", "UTG+1", "UTG+2", "LJ", "HJ", "CO", "BTN", "SB", "BB"],
  };

  function positions(size, button, occupied) {
    const order = [];
    for (let k = 1; k <= size; k++) {
      const seat = (button - 1 + k) % size + 1;
      if (occupied.indexOf(seat) >= 0) order.push(seat);
    }
    const n = order.length;
    const names = ORDER[n] || [];
    const out = {};
    order.forEach((seat, i) => { out[seat] = n === 2 ? (i === 0 ? "BB" : "BTN/SB") : names[(i - 2 + n) % n]; });
    return out;
  }

  function round1(x) { return Math.round(x * 10) / 10; }

  // players: one [name, stack, overrides] per seat, hero first; null is an empty seat.
  function seats(size, button, bb, players) {
    const occupied = [];
    players.forEach((player, i) => { if (player) occupied.push(i + 1); });
    const pos = positions(size, button, occupied);
    return players.map((player, i) => {
      const number = i + 1;
      if (!player) return {seat: number, empty: true};
      const more = player[2] || {};
      const bet = more.bet || 0;
      return Object.assign({
        seat: number, empty: false, is_hero: number === 1, name: player[0], pos: pos[number], is_button: number === button,
        stack: player[1], stack_bb: player[1] == null ? null : round1(player[1] / bb), stale: false, status: "active", type: "unknown", note: "",
        in_hand: true, folded: false, all_in: false, bet: bet, bet_bb: round1(bet / bb), is_target: false, delta: null,
      }, more);
    });
  }

  const HISTORY = [
    {no: 41, cards: "7c2d", pos: "HJ", advice: "FOLD", did: "fold", deviated: false, net: -75, text: "#41 7c2d HJ 300/600: coach FOLD, you fold. -75"},
    {no: 40, cards: "AsQs", pos: "UTG+1", advice: "RAISE", did: "raise", deviated: false, net: 2400, text: "#40 AsQs UTG+1 300/600: coach RAISE to 1,320, you raise. +2,400"},
    {no: 39, cards: "KhJd", pos: "UTG", advice: "FOLD", did: "raise", deviated: true, net: -1320, text: "#39 KhJd UTG 300/600: coach FOLD, you raise. -1,320 (deviated)"},
    {no: 38, cards: "9c9s", pos: "BB", advice: "CALL", did: "call", deviated: false, net: 9800, text: "#38 9c9s BB 250/500: coach CALL, you call. +9,800"},
    {no: 37, cards: "", pos: "SB", advice: null, did: null, deviated: false, net: -250, skipped: true, text: "#37 not recorded"},
  ];

  function tournament(opts) {
    const bb = opts.bb || 600;
    const level = Object.assign({number: 12, sb: bb / 2, bb: bb, ante: 75, ante_kind: "player", pending: null}, opts.level || {});
    return {
      rev: opts.rev || 128, mode: "tournament", unit: opts.unit || "chips", deck: opts.deck || "one-ink",
      can: {undo: true, redo: false},
      strip: Object.assign({
        level: level, remaining: 96, paid: 75, entrants: 500, start_stack: 10000, buyin: 11, avg_stack: 52100, avg_bb: 86.8,
        stage: {code: "approach", label: "21 from the money"}, icm: "estimated", style: "survive", plan: "full",
        opponents: "unknown", reentry_open: false, bounty: false, tally: null,
        payouts: [1000, 600, 400, 200, 200, 200],
      }, opts.strip || {}),
      table: {size: opts.size, button: opts.button, seats: seats(opts.size, opts.button, bb, opts.players)},
      hand: opts.hand || null,
      history: opts.history || HISTORY,
      toast: opts.toast || null,
      first_run: false,
      settings: {ladder: "turbo", ladders: [{name: "turbo", label: "Turbo"}, {name: "regular", label: "Regular"}],
                 levels: [[100, 200, 25], [150, 300, 40], [200, 400, 50], [300, 600, 75], [400, 800, 100]], size_limits: [2, 9]},
    };
  }

  function hand(more) {
    return Object.assign({
      no: 42, phase: "preflop", needs: "action", hero_cards: null, hero_class: null, board: [],
      pot: 0, pot_bb: 0, to_call: 0, to_call_bb: 0, target: 1, target_is_hero: true,
      legal: null, presets: [], line: [], pots: [], result: null,
    }, more);
  }

  // Events of the hand line, numbered as they come.
  function line(events) { return events.map((event, i) => Object.assign({i: i, auto: false}, event)); }
  function cards(text) { return {kind: "cards", street: "preflop", text: text}; }
  // The server writes the board with spaces and names the street: "Ks 7d 2c", flop.
  function board(text) {
    const street = {3: "flop", 1: "turn"}[text.split(" ").length] || "river";
    return {kind: "board", street: street, text: text};
  }
  function river(text) { return {kind: "board", street: "river", text: text}; }
  function act(seat, pos, name, verb, text, more) {
    return Object.assign({kind: "act", seat: seat, pos: pos, name: name, verb: verb, text: name + " " + text}, more || {});
  }
  function autoFold(seat, pos, name) { return act(seat, pos, name, "fold", "fold", {auto: true}); }

  /* A range written the usual way ("22+, A9s+, KTo+, 87s") as the 13 x 13 grid the chart draws. */

  const RANKS = "AKQJT98765432";
  function at(rank) { return RANKS.indexOf(rank); }

  function expand(token) {
    const out = [];
    let m;
    if ((m = /^([2-9TJQKA])\1(\+)?$/.exec(token))) {                      // 77 or 77+
      for (let i = m[2] ? 0 : at(m[1]); i <= at(m[1]); i++) out.push(RANKS[i] + RANKS[i]);
    } else if ((m = /^([2-9TJQKA])\1-([2-9TJQKA])\2$/.exec(token))) {     // TT-88
      for (let i = at(m[1]); i <= at(m[2]); i++) out.push(RANKS[i] + RANKS[i]);
    } else if ((m = /^([2-9TJQKA])([2-9TJQKA])([so])(\+)?$/.exec(token))) { // A9s or A9s+
      for (let i = m[4] ? at(m[1]) + 1 : at(m[2]); i <= at(m[2]); i++) out.push(m[1] + RANKS[i] + m[3]);
    } else if ((m = /^([2-9TJQKA])([2-9TJQKA])([so])-\1([2-9TJQKA])\3$/.exec(token))) { // A5s-A2s
      for (let i = at(m[2]); i <= at(m[4]); i++) out.push(m[1] + RANKS[i] + m[3]);
    }
    return out;
  }

  // spec: {r: "range that raises", c: "range that calls", x: "close hands"}; the rest folds.
  function grid(spec) {
    const code = {};
    ["r", "c", "x"].forEach((key) => {
      (spec[key] || "").split(",").forEach((token) => expand(token.trim()).forEach((name) => { code[name] = key; }));
    });
    const rows = [];
    for (let row = 0; row < 13; row++) {
      rows.push([]);
      for (let col = 0; col < 13; col++) {
        const name = row === col ? RANKS[row] + RANKS[col] : row < col ? RANKS[row] + RANKS[col] + "s" : RANKS[col] + RANKS[row] + "o";
        rows[row].push(code[name] || "f");
      }
    }
    return rows;
  }
  // Made-up numbers for the cell tooltips.
  function numbers(suffix) {
    const rows = [];
    for (let row = 0; row < 13; row++) {
      rows.push([]);
      for (let col = 0; col < 13; col++) rows[row].push(Math.max(28, 85 - 2 * (row + col) - (row > col ? 4 : 0)) + suffix);
    }
    return rows;
  }

  /* ---------- The usual table: eight seats, 300/600, hero in the cutoff ---------- */

  const EIGHT = [["You", 12900], ["Ann", 20400], ["Carl", 10920], ["Dee", 31260], ["Gus", 5640], ["Fox", 16200], ["Hal", 24180], ["Ivo", 9480]];
  function eight(overrides) {
    return EIGHT.map((player, i) => [player[0], player[1], (overrides || {})[i + 1] || {}]);
  }
  const FOLD = {folded: true};

  const OPEN_LINE = line([cards("AhKd"), autoFold(5, "UTG", "Gus"), autoFold(6, "UTG+1", "Fox"), autoFold(7, "LJ", "Hal"), autoFold(8, "HJ", "Ivo")]);
  const OPEN_LEGAL = {fold: true, check: false, call: 600, bet: null, raise: {min: 1200, max: 12900, default: 1320}, allin: 12900};
  const OPEN_PRESETS = [{label: "2.2x", to: 1320}, {label: "3x", to: 1800}, {label: "All-in", to: 12900}];

  function openView(more) {
    more = more || {};
    return tournament(Object.assign({
      size: 8, button: 2,
      players: eight({1: {is_target: true}, 3: {bet: 300}, 4: {bet: 600}, 5: FOLD, 6: FOLD, 7: FOLD, 8: FOLD}),
      hand: hand(Object.assign({
        hero_cards: ["Ah", "Kd"], hero_class: "AKo", pot: 1500, pot_bb: 2.5, to_call: 600, to_call_bb: 1,
        legal: OPEN_LEGAL, presets: OPEN_PRESETS, line: OPEN_LINE, pots: [{amount: 1500, eligible: [1, 2, 3, 4]}],
      }, more.hand || {})),
    }, more.view || {}));
  }

  const OPEN_CHART = {
    title: "Cutoff, first in, 21.5bb", share: 26, hero: "AKo",
    cells: grid({r: "22+, A2s+, K7s+, Q8s+, J8s+, T8s+, 97s+, 87s, 76s, 65s, A9o+, KTo+, QTo+, JTo", x: "K6s, Q7s, 96s, 86s, 75s, A8o, K9o, Q9o, J9o"}),
    numbers: null,
    legend: [{code: "r", label: "Raise"}, {code: "x", label: "Close"}, {code: "f", label: "Fold"}],
  };
  const CONTEXT = {
    stage: "Approaching the money: keep stealing, refuse marginal all-in calls.",
    gear: "16-25bb: raise-fold and re-shove.",
    fold_clock: "You can fold into the money.",
  };

  function openAdvice(more) {
    return Object.assign({
      rev: 128, status: "ready",
      headline: {verb: "RAISE", size_text: "TO 2.2BB \u00b7 1,320", qualifier: "", tone: "attack", sure: "standard", follow: {kind: "raise", to: 1320}},
      spot: "AhKd in the cutoff, 21.5bb, folded to you",
      reason: "The blinds are tight and you cover both. A raise keeps the fold option against an all-in.",
      tiles: [{label: "Open range here", value: "26%", note: "A9o+ is inside it", sign: 0},
              {label: "Fold to an all-in", value: "\u22122.2bb", note: "unless TT+, AQ+", sign: -1}],
      flip: "All-in instead under 16bb.",
      also: "All-in is close behind: +0.31bb.",
      source: "ICM estimated \u00b7 the all-in table agrees",
      plans: ["If BB (28bb) shoves: FOLD", "If BTN (34bb) re-raises small: ALL-IN"],
      warnings: [{code: "icm_estimated", text: "Payouts are estimated: enter the smallest prize for exact ICM."}],
      chart: OPEN_CHART,
      context: CONTEXT,
    }, more || {});
  }

  function none(spot, more) { return Object.assign({rev: 128, status: "none", spot: spot, context: CONTEXT, warnings: []}, more || {}); }

  /* ---------- The examples ---------- */

  const FIXTURES = {};
  function add(name, about, build) { FIXTURES[name] = {about: about, build: build}; }

  add("first-run", "No session yet: the tournament form", () => ({view: null, advice: null, ui: {}}));
  add("first-run-spin", "No session yet: Spin & Go", () => ({view: null, advice: null, ui: {setupMode: "spin"}}));
  add("first-run-aof", "No session yet: All-In or Fold", () => ({view: null, advice: null, ui: {setupMode: "aof"}}));

  add("first-run-view", "No hand recorded yet: the server sends a table and first_run", () => {
    const view = tournament({size: 8, button: 1, players: [["You", 10000], null, null, null, null, null, null, null]});
    view.first_run = true;
    view.setup = {level: "100/200", entrants: "1200"};
    return {view: view, advice: null, ui: {}};
  });

  add("between-hands", "Tournament, between hands", () => ({
    view: tournament({size: 8, button: 1, players: eight()}),
    advice: none("Press N, then type your two cards: A K S."),
  }));

  add("needs-cards", "A hand is dealt, hero's cards are missing", () => ({
    view: openView({hand: {hero_cards: null, hero_class: null, needs: "cards", line: []}}),
    advice: none("Type your two cards: A K S, or A H K D."),
  }));

  add("preflop-open", "Folded to hero: RAISE, with the chart", () => ({view: openView(), advice: openAdvice()}));

  add("hero-class", "Hero's cards known as a class (AKs)", () => ({
    view: openView({hand: {hero_cards: null, hero_class: "AKs", line: line([cards("AKs")].concat(OPEN_LINE.slice(1)))}}),
    advice: openAdvice({spot: "AKs in the cutoff, 21.5bb, folded to you", chart: Object.assign({}, OPEN_CHART, {hero: "AKs"})}),
  }));

  add("unit-bb", "The same spot with every number in big blinds", () => ({view: openView({view: {unit: "bb"}}), advice: openAdvice()}));

  add("updating", "An answer for an older table: greyed, Follow off", () => ({view: openView(), advice: openAdvice({rev: 127})}));

  add("no-advice", "The engine failed: NO ADVICE", () => ({
    view: openView(),
    advice: openAdvice({
      headline: {verb: "NO ADVICE", size_text: "", qualifier: "", tone: "wait", sure: "", follow: null},
      reason: "The engine stopped on this spot (KeyError: 'UTG+3'). Play it from the sheet; the next spot is advised as usual.",
      tiles: [], flip: "", also: "", source: "", plans: [], chart: null,
    }),
  }));

  add("advice-none", "Hero has raised; the small blind is next: WAIT", () => ({
    view: openView({
      view: {players: eight({1: {bet: 1320}, 2: FOLD, 3: {bet: 300, is_target: true}, 4: {bet: 600}, 5: FOLD, 6: FOLD, 7: FOLD, 8: FOLD})},
      hand: {pot: 2820, pot_bb: 4.7, to_call: 1020, to_call_bb: 1.7, target: 3, target_is_hero: false,
             legal: {fold: true, check: false, call: 1020, bet: null, raise: {min: 2040, max: 10920, default: 3960}, allin: 10920},
             presets: [{label: "3x", to: 3960}, {label: "All-in", to: 10920}],
             line: line(OPEN_LINE.concat([act(1, "CO", "You", "raise", "raise 2.2bb", {to: 1320}), autoFold(2, "BTN", "Ann")]))},
    }),
    advice: none("Carl (SB) has not acted yet."),
  }));

  add("strip-unset", "Players left and places paid are missing; a level is due", () => ({
    view: openView({view: {strip: {remaining: null, paid: null, avg_stack: null, avg_bb: null, icm: "off",
                                    stage: {code: "unknown", label: ""}},
                           level: {due: true, pending: {sb: 400, bb: 800, ante: 100}}}}),
    advice: openAdvice({source: "ICM off \u00b7 chip EV",
                        warnings: [{code: "icm_off", text: "ICM off: chip EV. Enter players left and places paid."}]}),
  }));

  // Hero in the big blind, nine-handed, against a button raise.
  function raiseView() {
    return tournament({
      size: 9, button: 8,
      players: [["You", 12000, {bet: 600, is_target: true}], ["Gus", 5640, FOLD], ["Fox", 16200, FOLD], ["Hal", 24180, FOLD], ["Ivo", 9480, FOLD],
                ["Jo", 7200, {folded: true, status: "away"}], ["Kim", 18000, FOLD], ["Ann", 15000, {bet: 1200}], ["Carl", 10920, {bet: 300, folded: true}]],
      hand: hand({
        hero_cards: ["Kc", "9h"], hero_class: "K9o", pot: 2775, pot_bb: 4.6, to_call: 600, to_call_bb: 1,
        legal: {fold: true, check: false, call: 600, bet: null, raise: {min: 1800, max: 12000, default: 3600}, allin: 12000},
        presets: [{label: "3x", to: 3600}, {label: "All-in", to: 12000}],
        line: line([cards("Kc9h"), autoFold(2, "UTG", "Gus"), autoFold(3, "UTG+1", "Fox"), autoFold(4, "UTG+2", "Hal"), autoFold(5, "LJ", "Ivo"),
                    autoFold(6, "HJ", "Jo"), autoFold(7, "CO", "Kim"), act(8, "BTN", "Ann", "raise", "raise 2bb", {to: 1200}), autoFold(9, "SB", "Carl")]),
        pots: [{amount: 2775, eligible: [1, 8]}],
      }),
    });
  }
  add("facing-raise", "Nine seats, a raise in front: CALL (close)", () => ({
    view: raiseView(),
    advice: {
      rev: 128, status: "ready",
      headline: {verb: "CALL", size_text: "1BB \u00b7 600", qualifier: "", tone: "passive", sure: "close", follow: {kind: "call"}},
      spot: "Kc9h in the big blind, 20bb, Ann (BTN) raises to 2bb",
      reason: "You are getting 4.6 to 1 and K9o has 39% against a button range.",
      tiles: [{label: "You need", value: "18%", note: "600 to win 2,775", sign: 0}, {label: "You have", value: "39%", note: "against 41% of hands", sign: 0}],
      flip: "Fold if the raise is 3bb or more, or against a nit.",
      also: "Folding gives up 0.3bb. An all-in over the top loses 0.44bb.",
      source: "ICM estimated \u00b7 guard not needed for a call of 1bb",
      plans: [],
      warnings: [{code: "close", text: "Close: before the money the lower-variance side leads."},
                 {code: "left_stale", text: "Players left is 12 hands old."}],
      chart: {title: "Big blind against a button raise, 20bb", share: 58, hero: "K9o",
              cells: grid({r: "33+, A8s+, ATo+, KTs+, QTs+, KQo", c: "22, A2s-A7s, A2o-A9o, K2s-K9s, Q2s-Q9s, J4s+, T6s+, 95s+, 85s+, 74s+, 64s+, 53s+, K8o, KJo, KTo, QTo+, JTo, T9o, 98o", x: "K9o, Q9o, J9o, T8o, 87o"}),
              numbers: numbers("%"),
              legend: [{code: "r", label: "All-in"}, {code: "c", label: "Call"}, {code: "x", label: "Close"}, {code: "f", label: "Fold"}]},
      context: CONTEXT,
    },
  }));

  // Hero in the big blind with 99, the cutoff is all-in for 15bb.
  function allinView(strip) {
    return tournament({
      size: 8, button: 7, strip: strip,
      players: [["You", 12000, {bet: 600, is_target: true}], ["Gus", 5640, FOLD], ["Fox", 16200, FOLD], ["Hal", 24180, FOLD], ["Ivo", 9480, FOLD],
                ["Kim", 0, {bet: 9000, all_in: true, stack_bb: 0}], ["Ann", 15000, FOLD], ["Carl", 10920, {bet: 300, folded: true}]],
      hand: hand({
        hero_cards: ["9c", "9s"], hero_class: "99", pot: 10500, pot_bb: 17.5, to_call: 8400, to_call_bb: 14,
        legal: {fold: true, check: false, call: 8400, bet: null, raise: null, allin: null}, presets: [],
        line: line([cards("9c9s"), autoFold(2, "UTG", "Gus"), autoFold(3, "UTG+1", "Fox"), autoFold(4, "LJ", "Hal"), autoFold(5, "HJ", "Ivo"),
                    act(6, "CO", "Kim", "allin", "all-in 15bb", {to: 9000}), autoFold(7, "BTN", "Ann"), autoFold(8, "SB", "Carl")]),
        pots: [{amount: 10500, eligible: [1, 6]}],
      }),
    });
  }
  const ALLIN_CHART = {title: "Big blind against a cutoff all-in, 15bb", share: 17, hero: "99",
                       cells: grid({r: "66+, A9s+, ATo+, KQs", x: "55, A8s, A9o, KJs"}), numbers: numbers("%"),
                       legend: [{code: "r", label: "Call"}, {code: "x", label: "Close"}, {code: "f", label: "Fold"}]};
  add("facing-allin-call", "An all-in in front: CALL (clear)", () => ({
    view: allinView(),
    advice: {
      rev: 128, status: "ready",
      headline: {verb: "CALL", size_text: "14BB \u00b7 8,400", qualifier: "", tone: "passive", sure: "clear", follow: {kind: "call"}},
      spot: "9c9s in the big blind, 20bb, Kim (CO) is all-in for 15bb",
      reason: "You need 47% and have 60% against the 22% of hands a cutoff shoves with 15bb.",
      tiles: [{label: "Need / have", value: "47% / 60%", note: "equity, price and ICM counted", sign: 0},
              {label: "Calling earns", value: "+1.9bb", note: "against folding", sign: 1}],
      flip: "Calling is right whenever they shove at least 12% of hands. Fold against a nit.",
      also: "", source: "ICM estimated \u00b7 the all-in table agrees (66+, A9s+, ATo+)", plans: [],
      warnings: [], chart: ALLIN_CHART, context: CONTEXT,
    },
  }));
  add("facing-allin-fold", "The same all-in on the bubble: FOLD (survival)", () => ({
    view: allinView({remaining: 152, paid: 150, entrants: 1000, stage: {code: "bubble", label: "Bubble"}}),
    advice: {
      rev: 128, status: "ready",
      headline: {verb: "FOLD", size_text: "", qualifier: "survival fold", tone: "fold", sure: "clear", follow: {kind: "fold"}},
      spot: "9c9s in the big blind, 20bb, Kim (CO) is all-in for 15bb",
      reason: "On the bubble the call table wants TT+, AQs+, AKo against a cutoff all-in. 99 is one notch short.",
      tiles: [{label: "Need / have", value: "53% / 60%", note: "the engine alone would call", sign: 0},
              {label: "A bust costs", value: "\u221214.0bb", note: "and the min-cash, 2 places away", sign: -1}],
      flip: "CALL once the bubble has burst, or against a player tagged maniac.",
      also: "", source: "ICM estimated \u00b7 SURVIVAL FOLD (engine: CALL, 60% against 53%)", plans: [],
      warnings: [{code: "icm_estimated", text: "Payouts are estimated: enter the smallest prize for exact ICM."}],
      chart: Object.assign({}, ALLIN_CHART, {title: "Bubble: big blind against a cutoff all-in", share: 5, cells: grid({r: "TT+, AQs+, AKo", x: "99, AJs, AQo"})}),
      context: {stage: "Bubble: calling an all-in needs a premium. Do not fight the big stack.",
                gear: "16-25bb: raise-fold and re-shove.", fold_clock: "You can fold into the money: 9 orbits of blinds, the bubble needs about 3."},
    },
  }));

  // Six seats, hero in the big blind facing a bet on the flop.
  function flopView(more) {
    return tournament(Object.assign({
      size: 6, button: 5,
      players: [["You", 13200, {is_target: true}], ["Gus", 5640, FOLD], ["Fox", 16200, FOLD], ["Hal", 24180, FOLD], ["Ann", 18600, {bet: 1140}], ["Carl", 10620, FOLD]],
      hand: hand({
        phase: "flop", hero_cards: ["Qh", "Jh"], hero_class: "QJs", board: ["Th", "9h", "2c"],
        pot: 4500, pot_bb: 7.5, to_call: 1140, to_call_bb: 1.9,
        legal: {fold: true, check: false, call: 1140, bet: null, raise: {min: 2280, max: 13200, default: 3900}, allin: 13200},
        presets: [{label: "Min", to: 2280}, {label: "1/2", to: 3390}, {label: "2/3", to: 4140}, {label: "Pot", to: 5640}, {label: "All-in", to: 13200}],
        line: line([cards("QhJh"), autoFold(2, "LJ", "Gus"), autoFold(3, "HJ", "Fox"), autoFold(4, "CO", "Hal"),
                    act(5, "BTN", "Ann", "raise", "raise 2.2bb", {to: 1320}), autoFold(6, "SB", "Carl"), act(1, "BB", "You", "call", "call"),
                    board("Th 9h 2c"), act(1, "BB", "You", "check", "check"), act(5, "BTN", "Ann", "bet", "bet 1,140", {to: 1140})]),
        pots: [{amount: 4500, eligible: [1, 5]}],
      }),
    }, more || {}));
  }
  const FLOP_ADVICE = {
    rev: 128, status: "ready",
    headline: {verb: "ALL-IN", size_text: "22BB \u00b7 13,200", qualifier: "semi-bluff", tone: "attack", sure: "standard", follow: {kind: "allin"}},
    spot: "QhJh on Th9h2c, Ann (BTN) bets 1.9bb into 5.6bb",
    reason: "A straight draw and a flush draw: 15 outs. With 3 pots behind they can fold, and you have 64% when called.",
    tiles: [{label: "Equity", value: "64%", note: "against a raise-then-bet range", sign: 0}, {label: "Outs", value: "15", note: "9 hearts, 6 more for the straight", sign: 0}],
    flip: "With more than 4 pots behind, call instead.",
    also: "", source: "ICM estimated \u00b7 after the flop the engine decides alone", plans: [], warnings: [], chart: null, context: CONTEXT,
  };
  add("flop-bet", "A bet faced on the flop: ALL-IN (semi-bluff)", () => ({view: flopView(), advice: FLOP_ADVICE}));
  add("four-colour", "The same flop with the four-colour deck", () => ({view: flopView({deck: "four-colour"}), advice: FLOP_ADVICE}));

  add("needs-board", "The betting is closed: the flop is wanted", () => ({
    view: openView({
      view: {players: eight({1: {bet: 0}, 2: FOLD, 3: FOLD, 5: FOLD, 6: FOLD, 7: FOLD, 8: FOLD})},
      hand: {needs: "board", phase: "flop", pot: 3540, pot_bb: 5.9, to_call: 0, to_call_bb: 0, target: null, target_is_hero: false, legal: null, presets: [],
             line: line(OPEN_LINE.concat([act(1, "CO", "You", "raise", "raise 2.2bb", {to: 1320}), autoFold(2, "BTN", "Ann"), autoFold(3, "SB", "Carl"), act(4, "BB", "Dee", "call", "call")]))},
    }),
    advice: none("Type the flop: K S 7 D 2 C."),
  }));

  add("needs-turn", "The flop is checked through: the turn is wanted", () => ({
    view: flopView({
      players: [["You", 13200], ["Gus", 5640, FOLD], ["Fox", 16200, FOLD], ["Hal", 24180, FOLD], ["Ann", 19740], ["Carl", 10620, FOLD]],
      hand: hand({phase: "turn", needs: "board", hero_cards: ["Qh", "Jh"], hero_class: "QJs", board: ["Th", "9h", "2c"], pot: 3360, pot_bb: 5.6,
                  target: null, target_is_hero: false,
                  line: line([cards("QhJh"), act(5, "BTN", "Ann", "raise", "raise 2.2bb", {to: 1320}), act(1, "BB", "You", "call", "call"),
                              board("Th 9h 2c"), act(1, "BB", "You", "check", "check"), act(5, "BTN", "Ann", "check", "check")])}),
    }),
    advice: none("Type the turn card: T H."),
  }));

  // Seven seats, three players at a showdown, one of them all-in for less.
  function showdownPlayers(done) {
    return [["You", done ? 26950 : 13850, done ? {delta: 7550} : {}], ["Gus", 5640, FOLD], ["Hal", 24180, FOLD],
            done ? null : ["Dee", 0, {all_in: true, stack_bb: 0}], ["Ann", 18600, FOLD],
            ["Fox", 11650, done ? {delta: -4550} : {}], ["Ivo", 9480, FOLD]];
  }
  const SHOWDOWN_LINE = line([cards("AsKh"), act(1, "UTG", "You", "raise", "raise 2.2bb", {to: 1320}), act(4, "CO", "Dee", "allin", "all-in 5bb", {to: 3000}),
                              act(6, "SB", "Fox", "call", "call"), act(1, "UTG", "You", "call", "call"), board("Ks 7d 2c"),
                              act(6, "SB", "Fox", "check", "check"), act(1, "UTG", "You", "bet", "bet 2,000", {to: 2000}), act(6, "SB", "Fox", "call", "call"),
                              board("Th"), act(6, "SB", "Fox", "check", "check"), act(1, "UTG", "You", "check", "check"), river("3s"),
                              act(6, "SB", "Fox", "check", "check"), act(1, "UTG", "You", "check", "check")]);
  function showdownHand(more) {
    return hand(Object.assign({
      phase: "showdown", needs: "result", hero_cards: ["As", "Kh"], hero_class: "AKo", board: ["Ks", "7d", "2c", "Th", "3s"],
      pot: 13100, pot_bb: 21.8, target: null, target_is_hero: false, line: SHOWDOWN_LINE,
      pots: [{amount: 9100, eligible: [1, 4, 6]}, {amount: 4000, eligible: [1, 6]}],
    }, more || {}));
  }
  add("showdown", "Showdown with a side pot: who won?", () => ({
    view: tournament({size: 7, button: 5, players: showdownPlayers(false), hand: showdownHand()}),
    advice: none("W if you won, L if you lost, or click the winner."),
  }));
  add("hand-done", "The hand is settled: stacks moved, a player is out", () => ({
    view: tournament({size: 7, button: 5, players: showdownPlayers(true), strip: {remaining: 95},
                      hand: showdownHand({phase: "done", needs: "next", result: {text: "You win 13,100: the main pot and the side pot."}}),
                      toast: {text: "Dee is out. 95 players left.", undo: true}}),
    advice: none("You win 13,100: the main pot and the side pot."),
  }));

  // Every pod state on one table.
  add("pod-states", "Folded, all-in, away, empty, unsure stack, next to act, a long name, a note", () => ({
    view: tournament({
      size: 9, button: 9,
      players: [["You", 12900, {bet: 600}], ["Ann", 20400, FOLD], ["Carl", 0, {bet: 10920, all_in: true, stack_bb: 0}],
                ["Dee", 31260, {status: "away", folded: true}], null, ["Fox", 16200, {stale: true}], ["Hal", 24180, {is_target: true}],
                ["Maximiliano_Fernandez_1987", 48300, {bet: 2400, type: "lag", note: "3-bets the button a lot"}], ["Ivo", 1250000, {type: "station", bet: 300}]],
      hand: hand({
        hero_cards: ["Ts", "Td"], hero_class: "TT", pot: 14820, pot_bb: 24.7, to_call: 10920, to_call_bb: 18.2, target: 7, target_is_hero: false,
        legal: {fold: true, check: false, call: 10920, bet: null, raise: {min: 19440, max: 24180, default: 24180}, allin: 24180},
        presets: [{label: "All-in", to: 24180}],
        line: line([cards("TsTd"), autoFold(2, "UTG", "Ann"), act(3, "UTG+1", "Carl", "allin", "all-in 18.2bb", {to: 10920}), autoFold(4, "UTG+2", "Dee")]),
        pots: [{amount: 14820, eligible: [1, 3, 6, 7, 8, 9]}],
      }),
    }),
    advice: none("Hal (HJ) has not acted yet."),
  }));

  // A final table with stacks in the millions and long names.
  add("millions", "Final table: millions, long names, big-blind ante", () => ({
    view: tournament({
      size: 9, button: 6, bb: 200000,
      level: {number: 41, ante: 200000, ante_kind: "bb"},
      strip: {remaining: 9, paid: 150, entrants: 12480, start_stack: 20000, buyin: 55, avg_stack: 27733000, avg_bb: 138.7,
              stage: {code: "final", label: "Final table"}, icm: "exact"},
      players: [["You", 4350000, {is_target: true}], ["Aleksandr_Volkov", 18600000, {bet: 440000, type: "lag"}], ["xX_RiverRat_Xx", 1250000, FOLD],
                ["Bartholomew", 96400000, FOLD], ["Jo", 2050000, FOLD], ["WWWWWWWWWWWW", 31800000, FOLD], ["Ann", 12750000, {bet: 100000, folded: true}],
                ["O'Neil <b>", 7400000, {bet: 200000}], ["Carl", 75000000, FOLD]],
      hand: hand({
        hero_cards: ["As", "Qs"], hero_class: "AQs", pot: 940000, pot_bb: 4.7, to_call: 440000, to_call_bb: 2.2,
        legal: {fold: true, check: false, call: 440000, bet: null, raise: {min: 680000, max: 4350000, default: 1320000}, allin: 4350000},
        presets: [{label: "3x", to: 1320000}, {label: "All-in", to: 4350000}],
        line: line([cards("AsQs"), act(2, "LJ", "Aleksandr_Volkov", "raise", "raise 2.2bb", {to: 440000}), autoFold(3, "HJ", "xX_RiverRat_Xx"),
                    autoFold(4, "CO", "Bartholomew"), autoFold(5, "BTN", "Jo"), autoFold(6, "SB", "WWWWWWWWWWWW")]),
        pots: [{amount: 940000, eligible: [1, 2, 8]}],
      }),
      history: [{no: 733, cards: "KdKc", pos: "UTG", advice: "RAISE", did: "raise", deviated: false, net: 1250000, text: "#733 KdKc UTG: coach RAISE, you raise. +1,250,000"}],
    }),
    advice: {
      rev: 128, status: "ready",
      headline: {verb: "RE-RAISE ALL-IN", size_text: "21.8BB \u00b7 4,350,000", qualifier: "", tone: "attack", sure: "clear", follow: {kind: "allin"}},
      spot: "AsQs in the hijack, 21.8bb, Aleksandr_Volkov (LJ) raises to 2.2bb",
      reason: "He opens wide and covers you, but AQs has 54% when called and he folds two hands in three.",
      tiles: [{label: "All-in earns", value: "+1.83bb", note: "ICM counted, against folding", sign: 1},
              {label: "He calls with", value: "TT+, AQs+, AKo", note: "about 5% of hands", sign: 0}],
      flip: "Fold if he is a nit: his range is then 12%.",
      also: "", source: "ICM exact \u00b7 final table: the engine decides alone",
      plans: [], warnings: [{code: "bounty", text: "Bounties are not priced."}],
      chart: {title: "All-in over a lojack raise, 21.8bb", share: 9, hero: "AQs", cells: grid({r: "88+, AJs+, AQo+", x: "77, ATs, KQs, AJo"}), numbers: numbers("bb"),
              legend: [{code: "r", label: "All-in"}, {code: "x", label: "Close"}, {code: "f", label: "Fold"}]},
      context: {stage: "Final table: every jump is large. Let shorter stacks bust first.", gear: "16-25bb: raise-fold and re-shove.", fold_clock: ""},
    },
  }));

  /* Tables of every size, with a bet in front of every seat and a full board: the worst case for overlaps. */

  const CROWD = [["You", 12900], ["Ann", 20400], ["Carl", 10920], ["Dee", 31260], ["Gus", 5640], ["Fox", 16200], ["Hal", 24180], ["Ivo", 9480], ["Jo", 7200]];
  const CROWD_BETS = [1200, 600, 12900, 2400, 5640, 1200, 24180, 300, 600];
  function crowdView(size, params) {
    const button = Number(params.get("button")) || (size > 3 ? 2 : 1);
    const players = CROWD.slice(0, size).map((player, i) => [player[0], player[1], {bet: CROWD_BETS[i], all_in: i === 4 || i === 6, is_target: i === 0}]);
    return tournament({
      size: size, button: button, players: players,
      hand: hand({
        phase: "river", hero_cards: ["Ah", "Kd"], hero_class: "AKo", board: ["Ks", "7d", "2c", "Th", "3s"],
        pot: 124500, pot_bb: 207.5, to_call: 22980, to_call_bb: 38.3,
        legal: {fold: true, check: false, call: 11700, bet: null, raise: null, allin: 12900}, presets: [],
        line: line([cards("AhKd"), act(2, "BTN", "Ann", "raise", "raise 2.2bb", {to: 1320}), board("Ks 7d 2c"), board("Th"), river("3s")]),
        pots: [{amount: 80000, eligible: [1, 2, 3]}, {amount: 44500, eligible: [1, 2]}],
      }),
    });
  }
  [2, 3, 4, 5, 6, 7, 8, 9].forEach((size) => {
    add("seats-" + size, size + " seats, everybody with chips in front, five board cards", (params) => ({
      view: crowdView(size, params), advice: openAdvice({chart: null, spot: "AhKd on Ks7d2cTh3s"}),
    }));
  });

  /* Spin & Go. */

  function spinView(more) {
    return Object.assign({
      rev: 128, mode: "spin", unit: "chips", deck: "one-ink", can: {undo: true, redo: false},
      strip: {level: {number: 3, sb: 20, bb: 40, ante: 0, ante_kind: "none", pending: null}, remaining: null, paid: null, entrants: null,
              start_stack: 300, buyin: 5, avg_stack: null, avg_bb: null, stage: {code: "unknown", label: ""}, icm: "off", style: "maxev", plan: "full",
              opponents: "solid", reentry_open: false, bounty: false, tally: {games: 12, wins: 5},
              game: {start_stack: 300, over: null, hands: 4}},
      hand: null, history: [], toast: null,
      settings: {ladder: "spin", ladders: [{name: "spin", label: "Spin"}], levels: [[10, 20, 0], [15, 30, 0], [20, 40, 0]], size_limits: [3, 3]},
    }, more);
  }
  const SPIN_LEGEND = [{code: "r", label: "All-in"}, {code: "x", label: "Close"}, {code: "f", label: "Fold"}];
  add("spin-3", "Spin & Go, three-handed: ALL-IN from the button", () => ({
    view: spinView({
      table: {size: 3, button: 1, seats: seats(3, 1, 40, [["You", 480, {is_target: true}], ["Rui", 460, {bet: 20}], ["Lena", 340, {bet: 40}]])},
      hand: hand({hero_cards: ["Ks", "7s"], hero_class: "K7s", pot: 60, pot_bb: 1.5, to_call: 40, to_call_bb: 1,
                  legal: {fold: true, check: false, call: 40, bet: null, raise: {min: 80, max: 480, default: 88}, allin: 480},
                  presets: [{label: "2.2x", to: 88}, {label: "All-in", to: 480}], line: line([cards("Ks7s")]), pots: [{amount: 60, eligible: [1, 2, 3]}]}),
    }),
    advice: {
      rev: 128, status: "ready",
      headline: {verb: "ALL-IN", size_text: "12BB \u00b7 480", qualifier: "", tone: "attack", sure: "standard", follow: {kind: "allin"}},
      spot: "Ks7s on the button, 12bb effective, nobody has entered",
      reason: "One prize: a chip won is worth what a chip lost costs. K7s is inside the button's 33%.",
      tiles: [{label: "All-in against folding", value: "+0.05bb", note: "a small edge", sign: 1}, {label: "Button range", value: "33%", note: "9 to 12bb effective", sign: 0}],
      flip: "Against players who call too much: FOLD (the loose table stops at K9s).",
      also: "", source: "Spin table \u00b7 chip EV, no ICM, no guard", plans: [], warnings: [],
      chart: {title: "Button, nobody in, 9 to 12bb", share: 33, hero: "K7s",
              cells: grid({r: "22+, A2s+, K6s+, Q8s+, J7s+, T7s+, 97s+, 86s+, 76s, A2o+, KTo+, QTo+, JTo", x: "K5s, Q7s, K9o"}), numbers: numbers("bb"), legend: SPIN_LEGEND},
      context: {stage: "", gear: "Under 16bb: all-in or fold from the solved table.", fold_clock: ""},
    },
  }));
  add("spin-hu", "Spin & Go, heads-up: CALL an all-in in the big blind", () => ({
    view: spinView({
      table: {size: 2, button: 2, seats: seats(2, 2, 40, [["You", 320, {bet: 40, is_target: true}], ["Rui", 0, {bet: 840, all_in: true, stack_bb: 0}]])},
      hand: hand({hero_cards: ["Ac", "5d"], hero_class: "A5o", pot: 880, pot_bb: 22, to_call: 320, to_call_bb: 8,
                  legal: {fold: true, check: false, call: 320, bet: null, raise: null, allin: null}, presets: [],
                  line: line([cards("Ac5d"), act(2, "BTN/SB", "Rui", "allin", "all-in 21bb", {to: 840})]), pots: [{amount: 720, eligible: [1, 2]}]}),
      strip: Object.assign(spinView({}).strip, {level: {number: 4, sb: 20, bb: 40, ante: 0, ante_kind: "none", pending: null}, opponents: "loose"}),
    }),
    advice: {
      rev: 128, status: "ready",
      headline: {verb: "CALL", size_text: "8BB \u00b7 320", qualifier: "", tone: "passive", sure: "clear", follow: {kind: "call"}},
      spot: "Ac5d in the big blind, 9bb effective, Rui (BTN/SB) is all-in",
      reason: "Heads-up at 9bb the small blind shoves most hands. Any ace calls.",
      tiles: [{label: "Calling against folding", value: "+0.66bb", note: "", sign: 1}, {label: "You call", value: "45%", note: "of hands at 9 to 12bb", sign: 0}],
      flip: "", also: "", source: "Spin table \u00b7 chip EV", plans: [], warnings: [],
      chart: {title: "Big blind against an all-in, 9 to 12bb", share: 45, hero: "A5o",
              cells: grid({r: "22+, A2s+, K2s+, Q6s+, J8s+, T9s, A2o+, K5o+, Q9o+, JTo", x: "Q5s, J7s, K4o"}), numbers: null, legend: [{code: "r", label: "Call"}, {code: "x", label: "Close"}, {code: "f", label: "Fold"}]},
      context: {stage: "", gear: "", fold_clock: ""},
    },
  }));

  add("spin-hu-busted", "Spin & Gold after a bust: three seats, one without chips", () => ({
    view: spinView({
      table: {size: 3, button: 1, seats: seats(3, 1, 40, [["You", 560, {bet: 20, is_target: true}], ["Rui", 300, {bet: 40}],
                                                           ["Lena", 0, {status: "busted", in_hand: false, pos: "", stack_bb: 0}]])},
      hand: hand({hero_cards: [], hero_class: "Q8o", pot: 60, pot_bb: 1.5, to_call: 20, to_call_bb: 0.5,
                  legal: {fold: true, check: false, call: 20, bet: null, raise: {min: 80, max: 600, default: 88}, allin: 340},
                  presets: [{label: "2x", to: 80}, {label: "2.2x", to: 88}, {label: "All-in", to: 340}], line: line([cards("Q8o")]), pots: [{amount: 60, eligible: [1, 2]}]}),
    }),
    advice: none("The coach is working on this spot.", {rev: 127}),
  }));
  add("spin-over", "Spin & Gold: the game is won, a new one is offered", () => {
    const view = spinView({
      table: {size: 3, button: 2, seats: seats(3, 2, 40, [["You", 900], ["Rui", 0, {status: "busted", in_hand: false, pos: "", stack_bb: 0}],
                                                           ["Lena", 0, {status: "busted", in_hand: false, pos: "", stack_bb: 0}]])},
      history: [{no: 11, cards: "AcJd", pos: "BB", advice: "CALL", did: "call", deviated: false, net: 380, text: "#11 AcJd BB: coach CALL, you call. +380"}],
    });
    view.strip.tally = {games: 13, wins: 6};
    view.strip.game = {start_stack: 300, over: "won", hands: 11};
    return {view: view, advice: none("")};
  });

  /* All-In or Fold: four seats, every amount in big blinds. */

  function aofView(button, players, handMore, net) {
    return {
      rev: 128, mode: "aof", unit: "bb", deck: "one-ink", can: {undo: true, redo: false},
      strip: {level: {number: null, sb: 0.5, bb: 1, ante: 0, ante_kind: "none", pending: null}, remaining: null, paid: null, entrants: null,
              start_stack: 8, buyin: null, avg_stack: null, avg_bb: null, stage: {code: "unknown", label: ""}, icm: "off", style: "maxev", plan: "full",
              opponents: "solid", reentry_open: false, bounty: false, tally: {net_bb: net}},
      table: {size: 4, button: button, seats: seats(4, button, 1, players)},
      hand: hand(handMore), history: [], toast: null,
    };
  }
  add("aof-shove", "All-In or Fold: an all-in in front, FOLD", () => ({
    view: aofView(1, [["You", 8, {is_target: true}], ["Rui", 7.5, {bet: 0.5}], ["Lena", 7, {bet: 1}], ["Vik", 0, {bet: 8, all_in: true}]],
                  {hero_cards: ["As", "5s"], hero_class: "A5s", pot: 9.5, pot_bb: 9.5, to_call: 8, to_call_bb: 8,
                   legal: {fold: true, check: false, call: 8, bet: null, raise: null, allin: 8}, presets: [{label: "All-in", to: 8}],
                   line: line([cards("As5s"), act(4, "CO", "Vik", "allin", "all-in 8bb", {to: 8})]), pots: [{amount: 9.5, eligible: [1, 4]}]}, 3.4),
    advice: {
      rev: 128, status: "ready",
      headline: {verb: "FOLD", size_text: "", qualifier: "", tone: "fold", sure: "clear", follow: {kind: "fold"}},
      spot: "As5s on the button, 8bb, Vik (CO) is all-in",
      reason: "Behind a cutoff all-in the button calls with 66+, ATs+ and AJo+ only.",
      tiles: [{label: "Calling against folding", value: "\u22120.28bb", note: "the size of the decision", sign: -1}, {label: "Button calls", value: "8%", note: "of hands", sign: 0}],
      flip: "", also: "", source: "All-In or Fold table, solid opponents", plans: [], warnings: [],
      chart: {title: "Button, the cutoff is all-in", share: 8, hero: "A5s", cells: grid({r: "66+, ATs+, AJo+", x: "55, A9s, KQs, ATo"}), numbers: numbers("bb"),
              legend: [{code: "r", label: "Call"}, {code: "x", label: "Close"}, {code: "f", label: "Fold"}]},
      context: {},
    },
  }));
  add("aof-first", "All-In or Fold: first in from the small blind, a coin flip", () => ({
    view: aofView(4, [["You", 7.5, {bet: 0.5, is_target: true}], ["Lena", 4.5, {bet: 1}], ["Vik", 8, FOLD], ["Rui", 8, FOLD]],
                  {hero_cards: ["Qd", "4c"], hero_class: "Q4o", pot: 1.5, pot_bb: 1.5, to_call: 0.5, to_call_bb: 0.5,
                   legal: {fold: true, check: false, call: null, bet: null, raise: null, allin: 8},
                   line: line([cards("Qd4c"), autoFold(3, "CO", "Vik"), autoFold(4, "BTN", "Rui")]), pots: [{amount: 1.5, eligible: [1, 2]}]}, -1.2),
    advice: {
      rev: 128, status: "ready",
      headline: {verb: "ALL-IN", size_text: "8BB", qualifier: "coin flip", tone: "attack", sure: "close", follow: {kind: "allin"}},
      spot: "Qd4c in the small blind, 5.5bb effective",
      reason: "Against one short big blind almost every queen moves in.",
      tiles: [{label: "All-in against folding", value: "+0.04bb", note: "under 0.05bb: either play is fine", sign: 1}, {label: "Small blind shoves", value: "71%", note: "of hands at 5.5bb", sign: 0}],
      flip: "", also: "Folding is as good.", source: "All-In or Fold table, solid opponents", plans: [],
      warnings: [{code: "outside_tables", text: "Answered for the effective stack, 5.5bb: an approximation."}],
      chart: null, context: {},
    },
  }));

  /* The same tables with something open. */

  function withUi(base, about, ui) {
    add(about[0], about[1], (params) => {
      const example = FIXTURES[base].build(params);
      return {view: example.view, advice: example.advice, ui: Object.assign({}, example.ui || {}, ui)};
    });
  }
  withUi("preflop-open", ["ui-settings", "The settings sheet"], {sheet: "settings"});
  withUi("spin-3", ["ui-settings-spin", "The settings sheet in Spin & Go"], {sheet: "settings"});
  // The real key map comes from the server (defaults.py, in view.settings.keys); this is a short sample of its shape.
  const SAMPLE_KEYS = {
    table: [{keys: ["n"], do: "deal", text: "New hand, next hand"}, {keys: ["Space"], do: "follow", text: "Do what the coach says"},
            {keys: ["Backspace", "z", "Ctrl+z"], do: "undo", text: "Undo"}, {keys: ["+", "="], do: "blinds_up", text: "Blinds up"}],
    seat: [{keys: ["f", "c", "x", "b", "r", "a"], do: "act", text: "That player folds, calls, checks, bets, raises, moves all-in"},
           {keys: ["s"], do: "stack", text: "Stack"}],
    type: [{keys: ["n"], do: "nit", text: "Nit"}, {keys: ["g"], do: "tag", text: "Tight-aggressive"}],
  };
  add("ui-keys", "The keys (a sample of the key map)", (params) => {
    const example = FIXTURES["preflop-open"].build(params);
    example.view.settings = Object.assign({}, example.view.settings, {keys: SAMPLE_KEYS});
    return {view: example.view, advice: example.advice, ui: Object.assign({}, example.ui || {}, {sheet: "keys"})};
  });
  withUi("preflop-open", ["ui-history", "The hand history"], {sheet: "history"});
  withUi("preflop-open", ["ui-why", "Why and range as a sheet (narrow screens)"], {sheet: "why"});
  withUi("preflop-open", ["ui-new", "New tournament"], {sheet: "new"});
  withUi("preflop-open", ["ui-stacks", "Every stack at once"], {sheet: "stacks"});
  withUi("preflop-open", ["ui-range", "The range tab"], {panel: "range"});
  withUi("preflop-open", ["ui-seat-menu", "A seat's menu"], {seatMenu: 7, target: 7});
  withUi("preflop-open", ["ui-seat-hero", "Hero's menu"], {seatMenu: 1});
  withUi("pod-states", ["ui-seat-add", "An empty seat: add a player"], {seatMenu: 5});
  withUi("showdown", ["ui-seat-winner", "A seat's menu at the showdown"], {seatMenu: 6});
  withUi("showdown", ["ui-award-side", "The main pot is given: who is next best?"], {awardTiers: [[4]]});
  withUi("preflop-open", ["ui-table-menu", "The table tools"], {menu: "table"});
  withUi("needs-cards", ["ui-picker-hero", "The card picker for hero, one rank chosen"], {picker: {slot: "hero", cards: [], rank: "A", rank2: null}});
  withUi("needs-cards", ["ui-picker-class", "The card picker: two ranks, suited or offsuit"], {picker: {slot: "hero", cards: [], rank: "A", rank2: "K"}});
  withUi("needs-board", ["ui-picker-flop", "The card picker for the flop, one card in"], {picker: {slot: "flop", cards: ["Ks"], rank: "7", rank2: null}});
  withUi("preflop-open", ["ui-amount", "The amount row for a raise"], {amount: {kind: "raise", seat: 1}});
  withUi("flop-bet", ["ui-amount-flop", "The amount row with five presets"], {amount: {kind: "raise", seat: 1}});
  withUi("flop-bet", ["ui-event", "An event of the hand line selected"], {selected: 9});
  withUi("flop-bet", ["ui-event-cards", "The flop selected on the hand line"], {selected: 7});
  withUi("preflop-open", ["ui-edit-level", "The blinds being typed"], {edit: "level"});
  withUi("preflop-open", ["ui-target", "Recording a player in front of hero"], {target: 7});
  withUi("preflop-open", ["ui-toast", "An intent was refused"], {toast: {text: "The king of spades is already on the board.", fix: "Pick another card, or change the flop first."}});

  /* ---------- The switcher ---------- */

  const params = new URLSearchParams(window.location.search);
  const name = params.get("fixture");
  const state = {view: null, advice: null, ui: {}};

  function draw() { window.MenloUI.render(state.view, state.advice, state.ui); }

  function showIndex() {
    document.body.innerHTML = '<div style="max-width:640px;margin:24px auto;padding:0 16px;font:14px/1.5 Inter,Arial,sans-serif">' +
      '<h1 style="font:italic 800 32px/1 \'Barlow Semi Condensed\',Arial,sans-serif;text-transform:uppercase;margin:0 0 12px">Examples</h1>' +
      Object.keys(FIXTURES).map((key) =>
        '<p style="margin:0 0 6px"><a style="color:#fff;font-weight:600" href="?fixture=' + key + '">' + key + '</a> <span style="color:#9A9AA3">' +
        FIXTURES[key].about + '</span></p>').join("") + '</div>';
  }

  function addSwitcher() {
    const select = document.createElement("select");
    select.setAttribute("aria-label", "Example");
    select.style.cssText = "position:fixed;right:8px;bottom:8px;z-index:99;height:28px;max-width:180px;background:#151518;color:#C9C9D1;" +
                           "border:1px solid #3A3A42;border-radius:8px;font:500 12px Inter,Arial,sans-serif";
    Object.keys(FIXTURES).forEach((key) => {
      const option = document.createElement("option");
      option.value = key;
      option.textContent = key;
      option.selected = key === name;
      select.appendChild(option);
    });
    select.addEventListener("change", () => {
      params.set("fixture", select.value);
      window.location.search = params.toString();
    });
    document.body.appendChild(select);
  }

  function start() {
    window.MenloFixture = {names: Object.keys(FIXTURES), state: state, draw: draw};
    if (!FIXTURES[name]) { showIndex(); return; }
    const example = FIXTURES[name].build(params);
    state.view = example.view;
    state.advice = example.advice;
    state.ui = example.ui || {};
    if (state.view && params.get("unit")) state.view.unit = params.get("unit");
    if (state.view && params.get("deck")) state.view.deck = params.get("deck");

    document.addEventListener("menlo:event", (event) => {
      const detail = event.detail;
      if (detail.ui) state.ui = Object.assign({}, state.ui, detail.ui);
      // No server here: show what would have been sent.
      if (detail.op) {
        const shown = Object.assign({}, detail);
        delete shown.ui;
        state.ui = Object.assign({}, state.ui, {toast: {text: "Would send " + JSON.stringify(shown)}});
      }
      draw();
    });
    document.addEventListener("keydown", (event) => {
      if (event.key !== "Escape") return;
      const patch = window.MenloUI.closeTopPatch(state.ui);
      if (patch) { state.ui = Object.assign({}, state.ui, patch); draw(); }
    });
    window.MenloUI.mount();
    draw();
    if (params.get("chrome") !== "0") addSwitcher();
  }

  start();
})();
