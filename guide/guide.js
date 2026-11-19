/* Menlo quick guide: the page.

   It works nothing out about poker before the flop: every answer is read from the tables in data.js, which
   tools/build_guide.py makes by asking the engine about each of the 169 hands of each spot.  What the page
   does itself: find the right table (LOOKUP), count how many hands take each action, work out the equity of
   a hand against the range the table names (from the engine's hand-against-hand numbers), apply the bubble
   rule, and the rules of thumb after the flop (POST), which are the playbook's.

   Seats are numbers: the players still to act behind you.  0 is the big blind, 1 the small blind, 2 the
   button.  The tables are made for nine players; a smaller table uses the last seats of that row. */
(function () {
  "use strict";

  const RANKS = "AKQJT98765432";
  const FIXED = ["BB", "SB", "BTN", "CO", "HJ", "LJ"];
  const PRESETS = [6, 8, 10, 12, 15, 20, 25, 30, 40, 50, 60, 100];
  const OPP = {unknown: "Standard", tight: "Tight", loose: "Loose"};
  const STYLE = {win: "Play to win", tag: "Tight"};
  const STAGE = {chips: "Normal", bubble: "Bubble"};
  const BUBBLE_POINTS = 0.10;           // on the bubble a call of an all-in needs this much equity over the price
  const MARK = '<svg class="mark" viewBox="0 0 40 40" role="img" aria-label="Menlo Bet"><rect width="40" height="40" rx="9" fill="#FFD60A"/>' +
               '<path d="M8 30V11l12 11 12-11v19h-5V22l-7 6.5L13 22v8z" fill="#0A0A0B"/></svg>';

  /* What can have happened before you act.  group 0: your first decision; 1: you raised first; 2: you re-raised. */
  const LINES = [
    {id: "open", group: 0, label: "Nobody in"},
    {id: "limp", group: 0, label: "Limpers"},
    {id: "raise", group: 0, label: "Raise"},
    {id: "allin", group: 0, label: "All-in"},
    {id: "raise3", group: 0, label: "Raise + re-raise"},
    {id: "raise_allin", group: 0, label: "Raise + all-in"},
    {id: "two_allin", group: 0, label: "2 all-ins"},
    {id: "re3", group: 1, label: "Re-raise"},
    {id: "re_allin", group: 1, label: "All-in"},
    {id: "re3_allin", group: 1, label: "Re-raise + all-in"},
    {id: "sq_allin", group: 2, label: "Raiser all-in"},
  ];
  const GROUPS = ["Before you", "You raised, then", "You re-raised, then"];
  /* Families where the answer is a call or a fold against chips that are already in: the bubble rule applies. */
  const CALL_FAMILIES = ["allin", "re_allin", "sq_allin", "raise_allin", "re3_allin", "hu_allin", "hu_re_allin"];

  let D = null, EQ = null, PAIRS = null;
  const unpacked = new Map();

  const DEFAULTS = {
    players: 8, seat: 2, stack: 25, r1: null, r2: null, suited: false,
    line: "open", from: 3, callers: 0, limpers: 1, by3: 0, byAll: 0,
    opp: "unknown", style: "win", stage: "chips",
    post: {role: "raiser", n: "hu", pos: "ip", street: "flop", hand: null, board: "dry", facing: "none", spr: "mid"},
  };
  let state = JSON.parse(JSON.stringify(DEFAULTS));

  /* ---------- small helpers ---------- */

  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
  const pct = (x) => Math.round(100 * x) + "%";
  const set = (patch) => ` data-set="${esc(JSON.stringify(patch))}"`;
  const bbText = (x) => (Math.round(x * 10) / 10) + "bb";

  function seatName(nb, players) {
    if (players === 2) return nb === 1 ? "SB" : "BB";
    if (nb <= 5) return FIXED[nb];
    const k = players - 1 - nb;
    return k ? "UTG+" + k : "UTG";
  }
  const range = (a, b) => { const out = []; for (let i = a; i >= b; i--) out.push(i); return out; };      // a down to b

  function handIndex(st) {
    if (st.r1 == null || st.r2 == null) return null;
    const hi = Math.min(st.r1, st.r2), lo = Math.max(st.r1, st.r2);
    if (hi === lo) return 14 * hi;
    return st.suited ? 13 * hi + lo : 13 * lo + hi;
  }
  const handName = (h) => D.hands[h];
  const combos = (h) => { const i = Math.floor(h / 13), j = h % 13; return i === j ? 6 : i < j ? 4 : 12; };

  function letters(table) {
    let out = unpacked.get(table);
    if (!out) {
      out = table.a.replace(/([A-Za-z])(\d+)/g, (m, ch, count) => ch.repeat(+count));
      unpacked.set(table, out);
    }
    return out;
  }
  /* A letter of a table -> {k: number of the action in D.actions, close} */
  function decode(ch) {
    let k = D.codes.indexOf(ch);
    if (k >= 0) return {k, close: false};
    return {k: D.close.indexOf(ch), close: true};
  }
  function equity(h, marks) {
    let weight = 0, sum = 0;
    for (let v = 0; v < 169; v++) {
      if (marks.charCodeAt(v) !== 49) continue;
      const n = PAIRS[h * 169 + v];
      weight += n;
      sum += n * EQ[h * 169 + v];
    }
    return weight ? sum / weight / 250 : null;
  }

  /* ---------- what the table can be: seats, lines and their choices ---------- */

  function can(line, st) {
    const n = st.players, h = st.seat;
    if (n === 2) return h === 1 ? ["open", "re3", "re_allin"].includes(line) : ["limp", "raise", "allin", "sq_allin"].includes(line);
    switch (line) {
      case "open": return h >= 1;
      case "limp": return h === 0 || h <= n - 2;
      case "raise": case "allin": case "sq_allin": return h <= n - 2;
      case "raise3": case "raise_allin": case "two_allin": return h <= n - 3;
      case "re3": case "re_allin": return h >= 1;
      case "re3_allin": return h >= 2;
    }
    return false;
  }
  /* The seats a line asks about ("raise from", "all-in from"), nearest to you last. */
  function fromSeats(line, st) {
    const n = st.players, h = st.seat;
    if (n === 2) return [];
    if (line === "raise" || line === "allin" || line === "sq_allin") return range(n - 1, h + 1);
    if (line === "raise3" || line === "raise_allin" || line === "two_allin") return range(n - 1, h + 2);
    return [];
  }
  function limperChoices(st) {
    const n = st.players, h = st.seat;
    if (n === 2) return [];
    const most = h === 0 ? Math.min(3, n - 2) : Math.min(3, n - 1 - h);
    const out = [];
    if (h === 0) out.push(0);                 // 0: the small blind only
    for (let k = 1; k <= most; k++) out.push(k);
    return out;
  }
  function by3Choices(st) {
    if (st.players === 2) return [];
    const out = [];
    if (st.seat >= 3) out.push(2);
    if (st.seat >= 2) out.push(1);
    if (st.seat >= 1) out.push(0);
    return out;
  }
  const byAllChoices = (st) => (st.players === 2 ? [] : range(st.seat - 1, 0));
  const defaultLine = (st) => (st.seat === 0 ? "raise" : "open");

  /* Make every choice fit the table: called after each change. */
  function normalize(st) {
    st.players = Math.max(2, Math.min(9, st.players | 0));
    st.seat = Math.max(0, Math.min(st.players - 1, st.seat | 0));
    st.stack = Math.max(1, Math.min(300, Math.round(+st.stack * 10) / 10 || 1));
    if (!D.opponents.includes(st.opp)) st.opp = D.opponents[0];
    if (!D.styles.includes(st.style)) st.style = D.styles[0];
    if (!STAGE[st.stage]) st.stage = "chips";
    if (!can(st.line, st)) st.line = defaultLine(st);
    if (!can(st.line, st)) st.line = LINES.map((l) => l.id).find((id) => can(id, st)) || "open";
    const seats = fromSeats(st.line, st);
    if (seats.length && !seats.includes(st.from)) {
      const want = Math.max(st.seat + (st.line === "raise" || st.line === "allin" || st.line === "sq_allin" ? 1 : 2), 2);
      st.from = seats.includes(want) ? want : seats[seats.length - 1];
    }
    if (st.line === "raise") st.callers = Math.max(0, Math.min(st.callers | 0, 2, st.from - st.seat - 1));
    const lim = limperChoices(st);
    if (lim.length && !lim.includes(st.limpers)) st.limpers = lim.includes(1) ? 1 : lim[0];
    const b3 = by3Choices(st);
    if (b3.length && !b3.includes(st.by3)) st.by3 = b3[b3.length - 1];
    const ba = byAllChoices(st);
    if (ba.length && !ba.includes(st.byAll)) st.byAll = 0;
    if (st.r1 != null && st.r1 === st.r2) st.suited = false;
    return st;
  }

  /* ---------- LOOKUP: state -> table ---------- */

  const rep = (o) => (o >= 6 ? 8 : o >= 4 ? 5 : o === 3 ? 3 : 2);      // the seats the three-way tables were made for
  const REP_NAME = {8: "an early seat", 5: "a middle seat", 3: "the cutoff", 2: "the button"};

  function tableOf(fam, key, st) {
    const f = D.index[fam];
    if (!f) return null;
    const s = f[st.style] || f[D.styles[0]];
    const o = s && (s[st.opp] || s[D.opponents[0]]);
    const id = o ? o[key.join(",")] : null;
    return id == null ? null : D.tables[id];
  }

  /* -> {fam, key, table, stack (the one the table was made for), notes} or {notes} when there is no table */
  function lookup(st, over) {
    st = over ? Object.assign({}, st, over) : st;
    const n = st.players, h = st.seat, notes = [];
    let fam = null, pre = [];
    if (n === 2) {
      fam = {open: "hu_open", re3: "hu_re3", re_allin: "hu_re_allin", limp: "hu_limp", raise: "hu_vsraise", allin: "hu_allin"}[st.line];
      if (st.line === "sq_allin") { fam = "sq_allin"; pre = [1, 0]; notes.push("Read from the table for three or more players."); }
    } else {
      switch (st.line) {
        case "open": fam = "open"; pre = [h]; break;
        case "limp":
          if (h === 0 && st.limpers === 0) fam = "limp_sb";
          else { fam = "limp"; pre = [h, st.limpers]; }
          break;
        case "raise":
          if (st.callers > 0 && st.stack <= 5) {
            fam = "two_allin"; pre = [rep(st.from)];
            notes.push("This short, a raise and a call are two all-ins: read from that table (made for the big blind).");
          } else { fam = "vsraise"; pre = [st.from, h, st.callers]; }
          break;
        case "raise3":
          fam = "raise3"; pre = [st.from];
          if (h !== 0) notes.push("Made for the big blind with the re-raise from the next seat; your own seat changes little.");
          break;
        case "allin": fam = "allin"; pre = [st.from, h]; break;
        case "raise_allin": case "two_allin":
          fam = st.line; pre = [rep(st.from)];
          if (h !== 0 || rep(st.from) !== st.from) notes.push(`Made for the big blind, with the first player in ${REP_NAME[rep(st.from)]} and the second in the next seat.`);
          break;
        case "re3": fam = "re3"; pre = [h, st.by3]; break;
        case "re_allin": fam = "re_allin"; pre = [h, st.byAll]; break;
        case "re3_allin":
          fam = "re3_allin"; pre = [rep(h)];
          notes.push(`Made for a raise from ${REP_NAME[rep(h)]}, a re-raise by the small blind and an all-in by the big blind.`);
          break;
        case "sq_allin": fam = "sq_allin"; pre = [st.from, h]; break;
      }
    }
    if (!fam || !D.index[fam]) return {notes: ["There is no table for this spot."]};
    const order = D.stacks.slice().sort((a, b) => Math.abs(a - st.stack) - Math.abs(b - st.stack) || a - b);
    for (const s of order) {
      const table = tableOf(fam, pre.concat([s]), st);
      if (!table) continue;
      if (s !== st.stack) {
        if (st.stack < s && (fam === "re3" || fam === "hu_re3" || fam === "sq_allin")) notes.push(`With ${bbText(st.stack)} a re-raise is an all-in. The nearest table is the one for ${s}bb.`);
        else if (st.stack > s && CALL_FAMILIES.concat(["two_allin"]).includes(fam) && s >= 40) notes.push(`An all-in bigger than ${s}bb is read at ${s}bb.`);
        else notes.push(`Read at ${s}bb, the nearest stack with a table.`);
      }
      return {fam, key: pre.concat([s]), table, stack: s, notes};
    }
    return {notes: ["There is no table for this spot."]};
  }

  /* The answers of a table as the page shows them: 169 x {k, close, name, bubble}.  On the bubble the close
     plays are folded (checked when the check is free) and a call of an all-in needs more than its price. */
  function answers(res, st) {
    const text = letters(res.table), out = [];
    const free = /[xX]/.test(text);
    const f = res.table.f || {};
    const marks = f.v != null ? D.ranges[f.v] : null;
    for (let h = 0; h < 169; h++) {
      const a = decode(text[h]);
      a.name = D.actions[a.k];
      if (st.stage === "bubble" && a.name !== "FOLD" && a.name !== "CHECK") {
        let why = null;
        if (a.close) why = "close";
        else if (marks && f.need != null && CALL_FAMILIES.includes(res.fam)) {
          const eq = equity(h, marks);
          if (eq != null && eq < f.need + BUBBLE_POINTS) why = "price";
        }
        if (why) { a.was = a.name; a.name = free ? "CHECK" : "FOLD"; a.k = D.actions.indexOf(a.name); a.bubble = why; a.close = false; }
      }
      out.push(a);
    }
    return out;
  }

  const KIND = {FOLD: "f", CHECK: "k", CALL: "c", LIMP: "c", RAISE: "r", RAISE_CALL: "rc", RERAISE: "r", RERAISE_BLUFF: "b", ALLIN: "j", ISOLATE: "r", ISOLATE_ALLIN: "j"};
  const ATTACK = ["RAISE", "RAISE_CALL", "RERAISE", "RERAISE_BLUFF", "ALLIN", "ISOLATE", "ISOLATE_ALLIN"];

  function sizeOf(name, table) {
    const z = table.z || {};
    const pick = (...keys) => { for (const k of keys) if (z[k] != null) return z[k]; return null; };
    if (name === "RAISE" || name === "RAISE_CALL") return pick("RAISE");
    if (name === "RERAISE" || name === "RERAISE_BLUFF") return pick("3-BET", "4-BET");
    if (name === "ISOLATE") return pick("RE-RAISE");
    return null;
  }
  /* -> [verb, size text] */
  function verbOf(name, table) {
    const size = sizeOf(name, table);
    const to = size != null ? "to " + bbText(size) : "";
    switch (name) {
      case "FOLD": return ["Fold", ""];
      case "CHECK": return ["Check", ""];
      case "CALL": return ["Call", ""];
      case "LIMP": return ["Call", "limp along"];
      case "RAISE": return ["Raise", to];
      case "RAISE_CALL": return ["Raise", to];
      case "RERAISE": case "RERAISE_BLUFF": case "ISOLATE": return ["Re-raise", to];
      case "ALLIN": case "ISOLATE_ALLIN": return ["All-in", ""];
    }
    return [name, ""];
  }
  const LEGEND = {FOLD: "Fold", CHECK: "Check", CALL: "Call", LIMP: "Call", RAISE: "Raise", RAISE_CALL: "Raise, call an all-in",
                  RERAISE: "Re-raise", RERAISE_BLUFF: "Re-raise as a bluff", ALLIN: "All-in", ISOLATE: "Re-raise", ISOLATE_ALLIN: "All-in"};

  /* Share of all hands that take each kind of action. */
  function shares(ans) {
    const by = {}; let all = 0;
    for (let h = 0; h < 169; h++) {
      const c = combos(h), key = LEGEND[ans[h].name];
      by[key] = by[key] || {n: 0, kind: KIND[ans[h].name]};
      by[key].n += c; all += c;
    }
    for (const k in by) by[k].share = by[k].n / all;
    return by;
  }

  /* ---------- words ---------- */

  function who3(st) { return st.by3 === 2 ? "a player behind you" : "the " + seatName(st.by3, st.players); }

  function spotTitle(st) {
    const n = st.players, me = seatName(st.seat, n), from = seatName(st.from, n);
    switch (st.line) {
      case "open": return `${me}, first in`;
      case "limp":
        if (n === 2 || (st.seat === 0 && st.limpers === 0)) return "BB, the small blind only called";
        return `${me} behind ${st.limpers} ${st.limpers > 1 ? "limpers" : "limper"}`;
      case "raise": return n === 2 ? "BB against a raise" : `${me} against a ${from} raise` + (st.callers ? ` and ${st.callers} ${st.callers > 1 ? "callers" : "caller"}` : "");
      case "raise3": return `${me} against a ${from} raise and a re-raise`;
      case "allin": return n === 2 ? "BB against an all-in" : `${me} against a ${from} all-in`;
      case "raise_allin": return `${me} against a ${from} raise and an all-in`;
      case "two_allin": return `${me} against two all-ins, the first from ${from}`;
      case "re3": return n === 2 ? "You raised, the BB re-raised" : `You raised from ${me}, ${who3(st)} re-raised`;
      case "re_allin": return n === 2 ? "You raised, the BB moved all-in" : `You raised from ${me}, the ${seatName(st.byAll, n)} moved all-in`;
      case "re3_allin": return `You raised from ${me}, a re-raise and an all-in`;
      case "sq_allin": return n === 2 ? "You re-raised the SB, who moved all-in" : `You re-raised the ${from}, who moved all-in`;
    }
    return me;
  }

  /* One sentence under the answer: why, in the table's own terms. */
  function reason(st, res, a, h, sh) {
    const n = st.players, me = seatName(st.seat, n), hand = handName(h), s = bbText(res.stack);
    const share = (label) => (sh[label] ? pct(sh[label].share) : "0%");
    const playing = pct(1 - (sh.Fold ? sh.Fold.share : 0) - (sh.Check ? sh.Check.share : 0));
    if (a.bubble === "close") return `On the bubble the close ones are let go: with chips only this is ${verbOf(a.was, res.table)[0].toLowerCase()}, by a small margin.`;
    if (a.bubble === "price") return `On the bubble a call needs ${Math.round(100 * BUBBLE_POINTS)} points more than its price: with chips only this is a call.`;
    const edge = a.close ? (a.name === "FOLD" || a.name === "CHECK" ? " Close: just outside the range, and fine to play against weak players." : " Close: the edge of the range. Let it go against strong players behind you.") : "";
    const fam = res.fam;
    if (fam === "open" || fam === "hu_open") {
      if (a.name === "RAISE") return `${hand} is in the ${me} opening range at ${s}: ${playing} of hands play here.` + edge;
      if (a.name === "RAISE_CALL") return `Raise small and call any all-in: at ${s} this hand wants the chips in, and a small raise lets worse hands move in.` + edge;
      if (a.name === "ALLIN") return `At ${s} this hand moves all-in from ${me}: a small raise would have to fold to an all-in or call it off anyway. ${share("All-in")} of hands move in here.` + edge;
      return `Outside the ${me} range at ${s}: ${playing} of hands play here.` + edge;
    }
    if (fam === "limp" || fam === "limp_sb" || fam === "hu_limp") {
      if (a.name === "RAISE") return `Raise over the ${fam === "limp" && st.limpers > 1 ? "callers" : "caller"}: ${hand} is ahead of the hands that only call.` + edge;
      if (a.name === "ALLIN") return `All-in over the ${fam === "limp" && st.limpers > 1 ? "callers" : "caller"}: there is dead money in the pot and a player who only called rarely has a hand that calls an all-in.` + edge;
      if (a.name === "LIMP") return "Call along: a hand for a cheap pot with several players. Go on after the flop only with a big hit." + edge;
      if (a.name === "CHECK") return "Check and see the flop for free: not strong enough to raise." + edge;
      return "Not strong enough to raise, and not a hand for calling along." + edge;
    }
    if (fam === "vsraise" || fam === "hu_vsraise") {
      if (a.name === "RERAISE") return `Re-raise for value: ${hand} is ahead of the raiser's range and can play for the whole stack.` + edge;
      if (a.name === "RERAISE_BLUFF") return "Re-raise as a bluff, with cards that make their best hands less likely. Fold if they move all-in." + edge;
      if (a.name === "ALLIN") return `All-in over the raise: at ${s} it takes the pot down often enough, and ${hand} has real equity when called.` + edge;
      if (a.name === "CALL") return (st.seat === 0 ? "Call: the big blind gets a good price and closes the action." : st.seat === 1 ? "Call from the small blind." : "Call in position: too good to fold, not strong enough to re-raise.") + edge;
      return `Fold: ${playing} of hands play against this raise, and ${hand} is not one of them.` + edge;
    }
    if (fam === "raise3") {
      if (a.name === "FOLD") return `Fold: a raise and a re-raise are two strong ranges. Only ${playing} of hands go on.` + edge;
      return `${hand} is one of the ${playing} of hands that go on against a raise and a re-raise.` + edge;
    }
    if (fam === "re3" || fam === "hu_re3") {
      if (a.name === "ALLIN") return `All-in over the re-raise: ${hand} is at the top of your raising range from ${me}.` + edge;
      if (a.name === "RERAISE") return "Re-raise again: this hand is never folded, and you call an all-in." + edge;
      if (a.name === "CALL") return "Call the re-raise. After the flop the stack goes in with an overpair, top pair or better." + edge;
      return `Fold to the re-raise: ${playing} of hands go on from ${me}.` + edge;
    }
    /* a call or a fold against chips that are in */
    if (a.name === "CALL" || a.name === "ALLIN" || a.name === "ISOLATE_ALLIN" || a.name === "ISOLATE") {
      const lead = a.name === "CALL" ? "Call" : a.name === "ISOLATE" ? "Re-raise to play against the all-in alone" : "All-in";
      return `${lead}: ${hand} has enough against the hands that do this.` + edge;
    }
    return `Fold: ${hand} does not have enough against the hands that do this.` + edge;
  }

  /* ---------- drawing ---------- */

  function chipRow(items, on, key, small) {
    return items.map(([value, label]) =>
      `<button class="chip${small ? " small" : ""}${value === on ? " on" : ""}" aria-pressed="${value === on}"${set({[key]: value})}>${esc(label)}</button>`).join("");
  }

  function inputsHtml(st) {
    const n = st.players;
    const seats = range(n - 1, 0).map((nb) => [nb, seatName(nb, n)]);
    const from = fromSeats(st.line, st).map((nb) => [nb, seatName(nb, n)]);
    let sub = "";
    if (st.line === "limp" && limperChoices(st).length > 1) {
      sub = `<div class="sub"><span class="eyebrow">Who called</span><div class="chips">${chipRow(limperChoices(st).map((k) => [k, k === 0 ? "SB only" : String(k)]), st.limpers, "limpers", true)}</div></div>`;
    } else if (from.length) {
      const label = {raise: "Raise from", allin: "All-in from", sq_allin: "Raise from", raise3: "First raise from", raise_allin: "Raise from", two_allin: "First all-in from"}[st.line];
      sub = `<div class="sub"><span class="eyebrow">${label}</span><div class="chips">${chipRow(from, st.from, "from", true)}</div></div>`;
      if (st.line === "raise") {
        const most = Math.min(2, st.from - st.seat - 1);
        if (most > 0) sub += `<div class="sub"><span class="eyebrow">Callers</span><div class="chips">${chipRow(range(most, 0).reverse().map((k) => [k, String(k)]), st.callers, "callers", true)}</div></div>`;
      }
    } else if (st.line === "re3" && by3Choices(st).length > 1) {
      sub = `<div class="sub"><span class="eyebrow">Re-raised by</span><div class="chips">${chipRow(by3Choices(st).map((w) => [w, w === 2 ? "A seat behind" : seatName(w, n)]), st.by3, "by3", true)}</div></div>`;
    } else if (st.line === "re_allin" && byAllChoices(st).length > 1) {
      sub = `<div class="sub"><span class="eyebrow">All-in from</span><div class="chips">${chipRow(byAllChoices(st).map((nb) => [nb, seatName(nb, n)]), st.byAll, "byAll", true)}</div></div>`;
    }
    const mine = LINES.find((l) => l.id === st.line).group;
    const groups = GROUPS.map((title, g) => {
      const chips = LINES.filter((l) => l.group === g && can(l.id, st));
      if (!chips.length) return "";
      return `<div class="group"><span class="eyebrow">${title}</span><div class="chips">${chipRow(chips.map((l) => [l.id, l.label]), st.line, "line")}</div>${g === mine ? sub : ""}</div>`;
    }).join("");
    const pair = st.r1 != null && st.r1 === st.r2;
    const slot = (r, next) => `<span class="slot${r != null ? " full" : ""}${next ? " next" : ""}">${r != null ? RANKS[r] : ""}</span>`;
    const first = st.r1 == null || st.r2 != null;         // the next rank tapped is the first card
    const keys = RANKS.split("").map((ch, i) => `<button class="key" data-rank="${i}" aria-label="${ch}">${ch}</button>`).join("") +
                 '<button class="key back" data-act="clear" aria-label="Clear the cards">Clear</button>';
    return `<div class="card">
      <div class="field">
        <div class="head"><span class="eyebrow">Your cards</span><span class="hint">tap two ranks, or a hand in the chart</span></div>
        <div class="cardsrow">${slot(st.r1, first)}${slot(st.r2, !first)}
          <span class="suit" role="group" aria-label="Suited or offsuit"><button class="${st.suited && !pair ? "on" : ""}"${pair ? " disabled" : ""}${set({suited: true})}>Suited</button><button class="${!st.suited && !pair ? "on" : ""}"${pair ? " disabled" : ""}${set({suited: false})}>Offsuit</button></span>
          <button class="clear" data-act="clear">Clear</button></div>
        <div class="keys">${keys}</div>
      </div>
      <div class="field">
        ${groups}
      </div>
      <div class="field">
        <div class="head"><span class="eyebrow">Your seat</span>
          <span class="stepper small" role="group" aria-label="Players at the table"><button data-act="fewer" aria-label="One player fewer">&minus;</button><span class="val">${n}</span><button data-act="more" aria-label="One player more">+</button><span class="hint">players</span></span></div>
        <div class="seats">${chipRow(seats, st.seat, "seat")}</div>
      </div>
      <div class="field">
        <div class="head"><span class="eyebrow">Stack in big blinds</span><span class="hint">the smaller of yours and theirs</span></div>
        <div class="stack"><span class="stepper"><button data-act="less" aria-label="One big blind less">&minus;</button>
          <input id="stack" type="number" inputmode="decimal" min="1" max="300" step="1" value="${st.stack}" aria-label="Stack in big blinds">
          <button data-act="plus" aria-label="One big blind more">+</button></span></div>
        <div class="presets">${chipRow(PRESETS.map((p) => [p, String(p)]), st.stack, "stack", true)}</div>
      </div>
      <div class="field">
        <div class="sub" style="margin-top:0"><span class="eyebrow">Opponents</span><div class="chips">${chipRow(D.opponents.map((o) => [o, OPP[o] || o]), st.opp, "opp", true)}</div></div>
        <div class="sub"><span class="eyebrow">Style</span><div class="chips">${chipRow(D.styles.map((s) => [s, STYLE[s] || s]), st.style, "style", true)}</div></div>
        <div class="sub"><span class="eyebrow">Stage</span><div class="chips">${chipRow(Object.keys(STAGE).map((s) => [s, STAGE[s]]), st.stage, "stage", true)}</div></div>
      </div>
    </div>`;
  }

  function factsHtml(st, res, h) {
    const f = res.table.f || {}, out = [];
    const vs = {vsraise: "They raise", hu_vsraise: "They raise", raise3: "The re-raise is", re3: "They re-raise", hu_re3: "They re-raise"}[res.fam] || "They do it with";
    if (f.vp != null) out.push(`<span class="fact">${vs}<b>${f.vp >= 10 ? Math.round(f.vp) : f.vp}%</b></span>`);
    if (h != null && f.v != null) {
      const eq = equity(h, D.ranges[f.v]);
      if (eq != null) out.push(`<span class="fact">You have about<b>${pct(eq)}</b></span>`);
    }
    const need = f.need != null ? f.need : f.odds;
    if (need != null) {
      const more = st.stage === "bubble" && f.need != null && CALL_FAMILIES.includes(res.fam);
      out.push(`<span class="fact">${more ? "On the bubble a call needs" : "A call needs"}<b>${pct(need + (more ? BUBBLE_POINTS : 0))}</b></span>`);
    }
    return out.length ? `<div class="facts">${out.join("")}</div>` : "";
  }

  function answerHtml(st, res, ans) {
    const n = st.players, h = handIndex(st);
    const where = `${seatName(st.seat, n)} &middot; ${bbText(st.stack)} &middot; ${n} players`;
    if (!res.table) return `<div class="slab idle"><div class="spot"><span>${where}</span></div><div class="row"><span class="verb">No table</span></div><div class="why">${esc(res.notes[0])}</div></div>`;
    const sh = shares(ans);
    if (h == null) {
      const parts = Object.keys(sh).filter((k) => k !== "Fold").sort((a, b) => sh[b].share - sh[a].share).map((k) => `${k.toLowerCase()} ${pct(sh[k].share)}`);
      const wait = st.r1 != null ? `${RANKS[st.r1]} and&hellip;` : "Your cards?";
      return `<div class="slab idle"><div class="spot"><span>${esc(spotTitle(st))}</span><span>${where}</span></div>
        <div class="row"><span class="verb">${wait}</span></div>
        <div class="why">${parts.length ? "This table: " + esc(parts.join(", ")) + "." : "Every hand folds here."} Tap two ranks.</div>${factsHtml(st, res, null)}</div>`;
    }
    const a = ans[h], [verb, size] = verbOf(a.name, res.table);
    const cls = ATTACK.includes(a.name) ? "attack" : a.name === "FOLD" ? "fold" : "passive";
    const tags = [];
    if (a.name === "RAISE_CALL") tags.push("call any all-in");
    if (a.name === "RERAISE_BLUFF") tags.push("fold to an all-in");
    if (a.close) tags.push("close");
    if (a.bubble) tags.push("bubble");
    return `<div class="slab ${cls}"><div class="spot"><span><b>${esc(handName(h))}</b> &middot; ${esc(spotTitle(st))}</span><span>${where}</span></div>
      <div class="row"><span class="verb">${verb}</span>${size ? `<span class="size">${esc(size)}</span>` : ""}${tags.map((t) => `<span class="tag">${t}</span>`).join("")}</div>
      <div class="why">${esc(reason(st, res, a, h, sh))}</div>${factsHtml(st, res, h)}</div>`;
  }

  function chartHtml(st, res, ans) {
    if (!res.table) return "";
    const me = handIndex(st), sh = shares(ans);
    let cells = "";
    for (let h = 0; h < 169; h++) {
      const a = ans[h], kind = KIND[a.name];
      const band = me == null && st.r1 != null && (Math.floor(h / 13) === st.r1 || h % 13 === st.r1);
      cells += `<button class="cell ${kind}${a.close ? " close" : ""}${h === me ? " me" : ""}${band ? " band" : ""}" data-hand="${h}" aria-label="${handName(h)}: ${LEGEND[a.name]}${a.close ? ", close" : ""}">${handName(h).slice(0, 2)}${h === me ? "" : ""}</button>`;
    }
    const order = ["Raise", "Raise, call an all-in", "Re-raise", "Re-raise as a bluff", "All-in", "Call", "Check", "Fold"];
    const legend = order.filter((k) => sh[k]).map((k) => {
      let label = k;
      const size = k === "Raise" ? sizeOf("RAISE", res.table) : k === "Re-raise" ? (sizeOf("RERAISE", res.table) || sizeOf("ISOLATE", res.table)) : null;
      if (size != null) label += " to " + bbText(size);
      return `<span><i class="${sh[k].kind}"></i>${esc(label)} ${pct(sh[k].share)}</span>`;
    }).join("");
    const notes = res.notes.map((t) => `<p class="hint">${esc(t)}</p>`).join("");
    return `<div class="card chart">
      <div class="head"><span class="title">${esc(spotTitle(st))} &middot; ${res.stack}bb</span></div>
      <div class="legend">${legend}</div>
      <div class="grid" role="group" aria-label="All 169 hands">${cells}</div>
      <div class="foot"><p class="hint">Suited hands above the diagonal, offsuit below. A cut corner marks a close one.${st.stage === "bubble" ? " Bubble rule applied." : ""}</p>${notes}</div>
    </div>`;
  }

  /* The answer in one line, for the bar that stays at the top of a phone once the answer has scrolled away. */
  function miniHtml(st, res, ans) {
    const h = handIndex(st);
    if (!res.table || h == null) return "";
    const a = ans[h], [verb, size] = verbOf(a.name, res.table);
    const cls = ATTACK.includes(a.name) ? "attack" : a.name === "FOLD" ? "fold" : "passive";
    return `<button class="minibar ${cls}" data-act="top" tabindex="-1"><b>${esc(handName(h))}</b><span class="verb">${verb}</span>` +
           `${size ? `<span class="size">${esc(size)}</span>` : ""}<span class="where">${seatName(st.seat, st.players)} &middot; ${bbText(st.stack)}</span></button>`;
  }

  /* What comes next, read from the follow-up tables for the same hand. */
  function planHtml(st, res, ans) {
    const h = handIndex(st);
    if (h == null || !res.table) return "";
    const a = ans[h], n = st.players, rows = [], rules = [];
    const row = (text, over, patch) => {
      const r = lookup(st, over);
      if (!r.table) return;
      const b = answers(r, Object.assign({}, st, over))[h], [verb, size] = verbOf(b.name, r.table);
      const cls = ATTACK.includes(b.name) ? "attack" : b.name === "FOLD" ? "fold" : "";
      rows.push(`<button class="planrow"${set(patch || over)}><span class="if">${esc(text)}</span><span class="then ${cls}">${verb}${size ? " " + esc(size.replace("to ", "")) : ""}<i class="go"></i></span></button>`);
    };
    const first = st.line === "open" || st.line === "limp";
    if (first && (a.name === "RAISE" || a.name === "RAISE_CALL") && st.seat >= 1) {
      if (a.name === "RAISE_CALL") rules.push("Any all-in behind you: call.");
      if (st.line === "limp") rules.push("These rows are read from the tables for a first raise: against a player who called and then re-raises, lean to the fold.");
      if (n === 2) {
        if (st.stack >= 12) row("The BB re-raises", {line: "re3"});
        row("The BB moves all-in", {line: "re_allin"});
      } else {
        if (st.stack >= 12) for (const w of by3Choices(st)) row(`Re-raised by ${w === 2 ? "a seat behind you" : "the " + seatName(w, n)}`, {line: "re3", by3: w});
        /* an all-in behind: seats with the same answer on one row */
        const groups = [];
        for (const v of byAllChoices(st)) {
          const r = lookup(st, {line: "re_allin", byAll: v});
          if (!r.table) continue;
          const b = answers(r, Object.assign({}, st, {line: "re_allin", byAll: v}))[h];
          const last = groups[groups.length - 1];
          if (last && last.name === b.name) last.seats.push(v); else groups.push({name: b.name, seats: [v]});
        }
        for (const g of groups) row(`All-in from ${g.seats.map((v) => seatName(v, n)).join(", ")}`, {line: "re_allin", byAll: g.seats[0]});
        if (st.seat >= 2 && st.stack >= 10) row("A re-raise and an all-in", {line: "re3_allin"});
      }
    } else if (st.line === "raise" && (a.name === "RERAISE" || a.name === "RERAISE_BLUFF")) {
      row(n === 2 ? "The SB moves all-in" : `The ${seatName(st.from, n)} moves all-in`, {line: "sq_allin"});
    } else if (a.name === "LIMP") {
      rules.push("If a player raises behind you: fold. With a pair and 15 times the raise behind, call once.");
    } else if (a.name === "CHECK") {
      rules.push("After the flop: bet top pair or better and strong draws; otherwise check, and fold to a bet.");
    } else if ((res.fam === "re3" || res.fam === "hu_re3") && a.name === "CALL") {
      rules.push("After the flop the stack goes in with an overpair, top pair or better.");
    } else if ((res.fam === "re3" || res.fam === "hu_re3") && a.name === "RERAISE") {
      rules.push("If they move all-in: call. This hand is never folded before the flop.");
    } else if ((res.fam === "vsraise" || res.fam === "hu_vsraise") && a.name === "CALL") {
      rules.push(st.seat <= 1 ? "After the flop you act first: check to the raiser, go on with a pair or a real draw, fold the rest to a bet."
                              : "After the flop you act last: go on with a pair or a real draw, and bet when the raiser checks twice.");
    }
    if (!rows.length && !rules.length) return "";
    return `<div class="card plan"><span class="eyebrow">If the hand goes on</span>
      <div class="rows">${rows.join("")}</div>${rules.map((t) => `<p class="rule">${esc(t)}</p>`).join("")}</div>`;
  }

  /* ---------- POST: after the flop, the playbook's rules of thumb ---------- */

  const POST_Q = [
    ["hand", "Your hand", [["monster", "Two pair or better"], ["top", "Overpair, or top pair good kicker"], ["mid", "Weaker pair"],
                            ["combo", "Big draw, 12+ outs"], ["draw", "Flush or open-ended draw"], ["weak", "Gutshot or overcards"], ["air", "Nothing"]]],
    ["facing", "The action to you", [["none", "No bet yet"], ["small", "Bet: a third of the pot or less"], ["half", "Bet: about half"], ["big", "Bet: two thirds or more"], ["raise", "I bet and was raised"]]],
    ["street", "Street", [["flop", "Flop"], ["turn", "Turn"], ["river", "River"]]],
    ["role", "Before the flop", [["raiser", "I raised last"], ["caller", "I called"]]],
    ["n", "Players", [["hu", "Two of us"], ["multi", "Three or more"]]],
    ["pos", "Position", [["ip", "I act last"], ["oop", "I act first"]]],
    ["board", "Board", [["dry", "Dry: K72, a pair, no draws"], ["wet", "Wet: connected or two of a suit"]]],
    ["spr", "Chips behind", [["low", "Under 1.5 pots"], ["mid", "1.5 to 4 pots"], ["deep", "Over 4 pots"]]],
  ];

  function postAdvice(p, bubble) {
    const hu = p.n === "hu", ip = p.pos === "ip", raiser = p.role === "raiser", wet = p.board === "wet";
    const flop = p.street === "flop", turn = p.street === "turn", river = p.street === "river";
    const low = p.spr === "low", deep = p.spr === "deep", short4 = !deep;
    const out = (verb, size, why) => ({verb, size, why});
    const made = p.hand === "monster" || p.hand === "top" || p.hand === "mid";
    let r;
    if (p.facing === "none") {
      switch (p.hand) {
        case "monster":
          r = out("Bet", low ? "half the pot, the rest next street" : wet || !flop ? "2/3 pot" : "1/2 pot",
                  "Bet for value on every street: you want the whole stack in. On a wet board never give a free card."); break;
        case "top":
          if (low) r = out("Bet", "1/2 pot or all-in", "Top pair or better with under 1.5 pots behind: the hand goes to showdown. Get the chips in and do not fold.");
          else if (river) r = out("Check", "", "One pair is a two-street hand. If you bet the flop and the turn, check now and call a bet of up to about 60% of the pot. If a street was checked through, bet half the pot for value.");
          else r = out("Bet", flop && !wet && hu ? "1/3 pot" : flop && !wet ? "1/2 pot" : "2/3 pot",
                       flop ? "Bet for value: worse pairs and draws call. Bigger on a wet board, small on a dry one." : "Bet again for value, and bigger on the turn: draws must pay. Check the river unless a street was checked.");
          break;
        case "mid":
          if (flop && raiser && hu && !wet) r = out("Bet", "1/3 pot", "As the raiser heads-up on a dry board, bet small with everything. On the turn check unless you improve.");
          else r = out("Check", "", "A hand for the showdown, not for betting: check, call one small bet, and fold to a big bet or a second one.");
          break;
        case "combo":
          if (river) r = out("Check", "", "The draw missed. Give up: bluff only heads-up against a player who folds, and never near the bubble.");
          else if (raiser || ip) r = out("Bet", "2/3 pot", short4 ? "A big draw bets when you raised before the flop or act last. With 4 pots or less behind, move all-in if you are raised: they fold some of the time and you have about " + (flop ? "45%" : "26%") + " when called."
                                                                  : "A big draw bets when you raised before the flop or act last: it wins the pot now or draws to the best hand.");
          else r = out("Check", "", short4 ? "Out of position without the lead: check. With 4 pots or less behind, move all-in over a bet on the flop." : "Out of position without the lead: check, and call a bet at the right price.");
          break;
        case "draw":
          if (river) r = out("Check", "", "The draw missed. Give up: no bluff into a player who called twice.");
          else if (flop && raiser && hu) r = out("Bet", "1/3 pot", "Your continuation bet with outs behind it: it wins the pot often and has 8 or 9 outs when called.");
          else r = out("Check", "", ip ? "Take the free card. Heads-up against a player who gives up often, a bet of half the pot is fine." : "Check, and call a bet at the right price: a third of the pot on any street, about half on the flop.");
          break;
        default:
          if (flop && raiser && hu && !wet) r = out("Bet", "1/3 pot", "A small continuation bet on a dry board works often enough with any two cards. If called, give up on the turn unless you improve.");
          else if (flop && raiser && hu) r = out("Check", "", "This board hits the hands that call a raise. Check and give up to a bet.");
          else r = out("Check", "", "Nothing to bet with: only the raiser's bet on the flop is a continuation bet. Check and fold to a bet.");
      }
    } else if (p.facing === "raise") {
      switch (p.hand) {
        case "monster":
          r = deep && !wet && ip ? out("Call", "", "Deep and in position on a dry board: call and let them keep betting. Raise the turn or the river.")
                                 : out(deep ? "Re-raise" : "All-in", "", "A raise against a very strong hand: get the stack in now, while worse hands and draws still pay."); break;
        case "top":
          if (low) r = out("All-in", "", "Top pair or better with under 1.5 pots behind: you are committed. The hand goes to showdown.");
          else if (flop) r = out("Fold", "", "A raise on the flop is rarely a bluff: fold one pair against a tight or passive player. Against an aggressive one call once, and fold to a big bet on the turn.");
          else r = out("Fold", "", "A raise on the turn or river beats one pair almost every time, above all from a passive player.");
          break;
        case "combo":
          if (flop && short4) r = out("All-in", "", "A big draw with 4 pots or less behind: move in. You have about 45% when called and they fold some of the time.");
          else if (flop) r = out("Call", "", "Too deep to move in: call, and go on when the draw comes or the price stays right.");
          else r = out("Fold", "", "One card to come gives about 26%: fold to a raise unless it costs a quarter of the pot or less.");
          break;
        default:
          r = out("Fold", "", made ? "A weak pair does not stand a raise." : "A raise takes the price away. Fold.");
      }
    } else {
      const small = p.facing === "small", half = p.facing === "half", big = p.facing === "big";
      switch (p.hand) {
        case "monster":
          if (river) r = out("Raise", low ? "all-in" : "about 3 times the bet", "Raise for value: they have shown a hand and will pay. All-in with under 2 pots behind.");
          else if (!wet && ip && deep) r = out("Call", "", "On a dry board in position: call and keep their bluffs in. Raise the turn.");
          else r = out(short4 ? "All-in" : "Raise", short4 ? "" : "about 3 times the bet", short4 ? "With 4 pots or less behind the stack goes in now, while draws and worse pairs still pay." : "Raise for value and to charge the draws.");
          break;
        case "top":
          if (low) r = out(river ? "Call" : "All-in", "", "Top pair or better with under 1.5 pots behind: you are committed. The hand goes to showdown.");
          else if (river && big) r = out("Fold", "", "A big bet on the river beats one pair too often: fold against a passive or unknown player. Against an aggressive one, call.");
          else r = out("Call", "", river ? "The price is right against busted draws and worse pairs." : "Call, one street at a time. Do not raise: only better hands go on. On the river fold to a big bet.");
          break;
        case "mid":
          if (flop && (small || half)) r = out("Call", "", "Call once. Fold on the turn to a second big bet unless you improve.");
          else if (flop) r = hu ? out("Call", "", "Heads-up against one bet, call once. Fold on the turn to a second big bet.") : out("Fold", "", "A weak pair against a big bet with several players in: fold.");
          else if (small) r = out("Call", "", "A small bet gives the price for a pair. Fold to a bigger one on the next street.");
          else r = out("Fold", "", "One weak pair is not worth a big bet on the " + (turn ? "turn" : "river") + ".");
          break;
        case "combo":
          if (river) r = out("Fold", "", "The draw missed.");
          else if (flop && short4) r = out("All-in", "", "A big draw with 4 pots or less behind: move in over the bet. You have about 45% when called and they fold some of the time.");
          else if (flop) r = out("Call", "", "Too deep to move in: call. You have about 45% with two cards to come.");
          else if (big && !deep) r = out("Fold", "", "One card to come gives about 26%, and a big bet needs 29% or more. Call only with more than 4 pots behind.");
          else r = out("Call", "", "About 26% with one card to come: the price is right.");
          break;
        case "draw":
          if (river) r = out("Fold", "", "The draw missed.");
          else if (flop && (small || half)) r = out("Call", "", "The price is right for 8 or 9 outs with two cards to come and chips behind.");
          else if (flop) r = low ? out("Call", "", "The bet is close to all-in, so you see both cards: about 35%, enough for a bet up to the size of the pot.")
                                 : ip ? out("Call", "", "In position with chips behind, a flush or open-ended draw calls one big bet. Fold the turn to another if it misses.")
                                      : out("Fold", "", "Out of position a big bet does not give the price: 19% for the next card against the 29% needed.");
          else if (small) r = out("Call", "", "A third of the pot needs 20%, and you have about 19% plus what you win when it comes.");
          else if (half && deep) r = out("Call", "", "Half the pot needs 25% and you have 19%: the chips behind make up the difference when you hit.");
          else r = out("Fold", "", "One card to come gives about 19%. This bet needs " + (half ? "25%" : "29% or more") + ".");
          break;
        case "weak":
          r = out("Fold", "", "Too few outs for the price. A gutshot with two overcards may call one small bet in position, no more."); break;
        default:
          r = out("Fold", "", "No pair and no draw: fold to a bet.");
      }
    }
    if (bubble && (r.verb === "Call" || r.verb === "Bet") && (p.hand === "mid" || p.hand === "air" || p.hand === "weak")) r.why += " Near the bubble: no bluffs over several streets and no thin calls for a third of your stack or more.";
    r.cls = ["Bet", "Raise", "Re-raise", "All-in"].includes(r.verb) ? "attack" : r.verb === "Fold" ? "" : "passive";
    return r;
  }

  function postHtml(st, open) {
    const p = st.post;
    const q = ([key, title, options]) =>
      `<div class="q"><span class="eyebrow">${title}</span><div class="chips">${options.map(([v, label]) =>
        `<button class="chip${p[key] === v ? " on" : ""}" aria-pressed="${p[key] === v}"${set({post: {[key]: v}})}>${esc(label)}</button>`).join("")}</div></div>`;
    let out = '<div class="out"><div class="why">Choose your hand to see the play.</div></div>';
    if (p.hand) {
      const r = postAdvice(p, st.stage === "bubble");
      out = `<div class="out ${r.cls}"><span class="verb">${r.verb}</span>${r.size ? `<span class="size">${esc(r.size)}</span>` : ""}<div class="why">${esc(r.why)}</div></div>`;
    }
    return `<details class="card post" id="post-box"${open ? " open" : ""}><summary><span class="title">After the flop</span><span class="hint">rules of thumb</span></summary>
      <div class="body">${POST_Q.slice(0, 2).map(q).join("")}${out}${POST_Q.slice(2).map(q).join("")}</div></details>`;
  }

  function notesHtml(open) {
    return `<details class="card notes" id="notes-box"${open ? " open" : ""}><summary><span class="title">How to read it</span><span class="hint">and what it is made of</span></summary>
      <div class="body">
        <p><b>Stack</b> is the effective one: the smaller of yours and the biggest stack that can still call you. Against an all-in it is the size of the all-in, or your stack if that is smaller.</p>
        <p><b>The answers</b> are the coach's engine asked about every hand of every spot, counting chips only, with a big blind ante. ${D.tables.length.toLocaleString("en")} tables, nothing is worked out while you play.</p>
        <p><b>Play to win</b> opens and defends wider than the coach's tight ranges. <b>Tight</b> is those ranges. Both take stacks as equal and know nothing about prizes.</p>
        <p><b>Bubble</b> folds the close ones and asks 10 points of equity more before calling an all-in. It is a rule of thumb, not a prize calculation: with the real stacks and prizes, the coach's own table app is exact.</p>
        <p><b>Opponents</b> changes the hands they are taken to raise and move in with: tight players fewer, loose players more.</p>
        <p><b>Three players in the pot</b> (a raise and an all-in, two all-ins) are made for the big blind and four first seats; the chart says so when your spot is read from a neighbour.</p>
        <p><b>After the flop</b> is the playbook's rules of thumb with pot-odds arithmetic, not a solver.</p>
        <p>A study aid. Most sites do not allow charts or outside help while you play for real money: check the rules of yours.</p>
      </div></details>`;
  }

  /* ---------- state, events ---------- */

  const $ = (id) => document.getElementById(id);
  let postOpen = false, notesOpen = false;

  function save() {
    try { localStorage.setItem("menlo-guide", JSON.stringify(state)); } catch (e) { /* private window: nothing is kept */ }
  }
  function load() {
    try {
      const saved = JSON.parse(localStorage.getItem("menlo-guide") || "null");
      if (saved && typeof saved === "object") {
        state = Object.assign({}, state, saved, {post: Object.assign({}, state.post, saved.post || {})});
      }
    } catch (e) { /* nothing saved, or not readable */ }
  }

  function render(keepInputs) {
    normalize(state);
    const res = lookup(state), ans = res.table ? answers(res, state) : null;
    if (!keepInputs) {
      const at = document.activeElement && document.activeElement.getAttribute && document.activeElement.getAttribute("data-set");
      $("inputs").innerHTML = inputsHtml(state);
      if (at) { const again = document.querySelector(`#inputs [data-set="${at.replace(/"/g, '\\"')}"]`); if (again) again.focus({preventScroll: true}); }
    }
    $("answer").innerHTML = answerHtml(state, res, ans);
    $("mini").innerHTML = miniHtml(state, res, ans);
    $("plan").innerHTML = planHtml(state, res, ans);
    $("chart").innerHTML = chartHtml(state, res, ans);
    $("post").innerHTML = postHtml(state, postOpen);
    if (!$("notes").innerHTML) $("notes").innerHTML = notesHtml(notesOpen);
    const next = $("btn-next");
    if (next) next.innerHTML = `Next hand <b>&rarr; ${seatName((state.seat + 1) % state.players, state.players)}</b>`;
    save();
  }

  function apply(patch) {
    for (const key in patch) {
      if (key === "post") Object.assign(state.post, patch.post);
      else state[key] = patch[key];
    }
    if ("seat" in patch && !("line" in patch) && !can(state.line, state)) state.line = defaultLine(state);
    if ("line" in patch && patch.line === "sq_allin") state.post.role = "raiser";
    render();
  }

  function pickRank(i) {
    if (state.r1 == null || state.r2 != null) { state.r1 = i; state.r2 = null; state.suited = false; }
    else state.r2 = i;
    render();
  }
  function nextHand() {
    state.seat = (state.seat + 1) % state.players;
    state.r1 = state.r2 = null; state.suited = false;
    state.line = defaultLine(state);
    state.post.hand = null; state.post.facing = "none"; state.post.street = "flop";
    render();
    window.scrollTo({top: 0});
  }
  function act(name) {
    if (name === "clear") { state.r1 = state.r2 = null; state.suited = false; }
    else if (name === "fewer" || name === "more") {
      const before = state.players;
      state.players = Math.max(2, Math.min(9, before + (name === "more" ? 1 : -1)));
      if (state.players === before) return;
      if (!can(state.line, normalize(state))) state.line = defaultLine(state);
    } else if (name === "less" || name === "plus") state.stack = Math.max(1, Math.min(300, Math.round(state.stack) + (name === "plus" ? 1 : -1)));
    else if (name === "next") return nextHand();
    else if (name === "top") return window.scrollTo({top: 0, behavior: "smooth"});
    render();
  }

  function onClick(event) {
    const el = event.target.closest("[data-set],[data-rank],[data-act],[data-hand]");
    if (!el || el.disabled) return;
    if (el.dataset.set) apply(JSON.parse(el.dataset.set));
    else if (el.dataset.rank != null) pickRank(+el.dataset.rank);
    else if (el.dataset.act) act(el.dataset.act);
    else if (el.dataset.hand != null) {
      const h = +el.dataset.hand, i = Math.floor(h / 13), j = h % 13;
      state.r1 = Math.min(i, j); state.r2 = Math.max(i, j); state.suited = i < j;
      render();
    }
  }
  function onInput(event) {
    if (event.target.id !== "stack") return;
    const value = parseFloat(event.target.value);
    if (!(value >= 1)) return;
    state.stack = value;
    render(true);
    document.querySelectorAll(".presets .chip").forEach((chip) => chip.classList.toggle("on", JSON.parse(chip.dataset.set).stack === state.stack));
  }
  function onKey(event) {
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    const tag = event.target.tagName;
    if (tag === "INPUT") { if (event.key === "Enter") event.target.blur(); return; }
    const key = event.key.length === 1 ? event.key.toUpperCase() : event.key;
    const rank = RANKS.indexOf(key === "1" ? "A" : key);
    if (key.length === 1 && rank >= 0) { pickRank(rank); event.preventDefault(); }
    else if (key === "S" || key === "O") { if (state.r1 !== state.r2 || state.r1 == null) apply({suited: key === "S"}); }
    else if (key === "Backspace" || key === "Delete") act("clear");
    else if (key === "ArrowUp") { act("plus"); event.preventDefault(); }
    else if (key === "ArrowDown") { act("less"); event.preventDefault(); }
    else if (key === "N") nextHand();
  }
  function onToggle(event) {
    if (event.target.id === "post-box") postOpen = event.target.open;
    if (event.target.id === "notes-box") notesOpen = event.target.open;
  }

  function start(data) {
    D = data;
    const bytes = (text) => Uint8Array.from(atob(text), (c) => c.charCodeAt(0));
    EQ = bytes(D.eq); PAIRS = bytes(D.pairs);
    load();
    const root = $("guide");
    root.innerHTML = `<header class="top"><div class="brand">${MARK}<span class="word">Menlo<b>.bet</b></span><span class="sub">Quick guide</span></div>
        <button class="next" id="btn-next" data-act="next"></button></header>
      <div class="cols">
        <div class="col left"><section id="inputs" aria-label="The spot"></section><section id="post"></section><section id="notes"></section></div>
        <div class="col right"><section id="answer" aria-live="polite" aria-label="The answer"></section><div id="mini" aria-hidden="true"></div><section id="plan"></section><section id="chart"></section></div>
      </div>
      <p class="foot">Menlo.bet quick guide &middot; a study aid &middot; tables v${D.version}${D.quick || D.partial ? " (trial set)" : ""}</p>`;
    root.addEventListener("click", onClick);
    root.addEventListener("input", onInput);
    root.addEventListener("toggle", onToggle, true);
    document.addEventListener("keydown", onKey);
    if ("IntersectionObserver" in window) {       // the one-line bar shows while the answer itself is out of sight
      new IntersectionObserver((entries) => $("mini").classList.toggle("on", !entries[0].isIntersecting && entries[0].boundingClientRect.top < 0),
                               {threshold: 0}).observe($("answer"));
      /* ... and not over the rules for after the flop, which are about another moment of the hand */
      new IntersectionObserver((entries) => $("mini").classList.toggle("off", entries[0].isIntersecting),
                               {rootMargin: "0px 0px -60% 0px"}).observe($("post"));
    }
    render();
  }

  /* For the tests: the page's own reading of a spot, without the page. */
  window.MenloGuide = {
    start, lookup: (st) => lookup(normalize(Object.assign(JSON.parse(JSON.stringify(DEFAULTS)), st))),
    answer(st, hand) {
      const full = normalize(Object.assign(JSON.parse(JSON.stringify(DEFAULTS)), st));
      const res = lookup(full);
      if (!res.table) return null;
      const a = answers(res, full)[D.hands.indexOf(hand)];
      return {fam: res.fam, key: res.key, name: a.name, close: a.close, size: sizeOf(a.name, res.table)};
    },
    equity: (hand, marks) => equity(D.hands.indexOf(hand), marks),
    postAdvice, state: () => state, seatName,
  };

  function boot() {
    if (window.GUIDE_DATA) return start(window.GUIDE_DATA);
    fetch("data.json").then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); }).then(start).catch(() => {
      $("guide").innerHTML = '<p class="loading">The tables did not load. Reload the page.</p>';
    });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot); else boot();
})();
