/* ==========================================================================================
   Menlo coach: the page, drawn from data. No poker rules and no server calls live here.

   ENTRY POINTS
     MenloUI.mount()                      Call once. Starts listening for clicks, Enter and the
                                          arrow keys inside the tabs, the table and the hand line.
     MenloUI.render(view, advice, ui)     Draws everything. Call it again whenever one of the
                                          three changes; a part whose HTML did not change is left
                                          alone, and the focus and a half-typed value survive.
         view     the JSON of GET /api/view (SPEC section 6); null, without "table", or with
                  first_run: true = the first-run form
         advice   the JSON of GET /api/advice (SPEC section 7); null while it is on its way
         ui       what is open on this screen only (never sent to the server), see UI STATE
     MenloUI.closeTopPatch(ui)            The ui patch that closes the topmost open thing (for Esc),
                                          or null when nothing is open.
     MenloUI.format                       The number formats used on the page (for your own toasts).
     MenloUI.pickerStep(view, picker, step)   One step of picking cards: what a click on the picker sends,
                                          and what the controller sends for a card key.
     MenloUI.isCurrent, actingSeat, seatOf, seatClick, spinOver, only, AFTER_ACT, freshPicker, NOTICE
                                          Small rules shared with the controller.

   EVENTS
     document.addEventListener("menlo:event", function (e) { ... e.detail ... })
     detail is plain data with up to three parts, and one click may carry more than one:
       op    an intent for POST /api/intent, with its arguments beside it: {op: "act", seat: 4, kind: "call"}
       ui    a patch for the ui object: ui = Object.assign({}, ui, detail.ui), then render again
       cmd   a job for the browser: "copy" (with text), "reload" (read the table from the program again)
     A typed value always travels as text and is parsed in Python ("12.5k", "300/600/75").
     Keys handled here: Enter in a field (sends it) and the arrow keys inside the mode tabs, the table
     and the hand line (they move the focus; the event is then defaultPrevented). Every other key is yours.

     op              arguments                                        comes from
     set_mode        mode: tournament | spin | aof                    the mode tabs
     undo, redo                                                       header, toast
     level_down, level_up                                             the blind steppers
     set_level       text                                             the blinds, typed ("300/600/75" or "600")
     remaining       step: -1 | 1, or text                            players left
     set_tournament  field, and text or value (true / false)          paid, entrants, start_stack, avg_stack,
                                                                      buyin, payouts, reentry_open, bounty
     set_config      key, value                                       style, plan, opponents, unit, deck, button_rule
     set_ante_kind   kind: none | player | bb                         settings
     set_ladder      text (one level per line), or name               settings
     set_size        size, clear: true to remove the players          table tools; the toast of a refused "- Seat"
                     sitting on the seats that go
     button_step     step: -1 | 1                                     table tools
     new_table       size, button                                     table tools, New table
     set_button      seat                                             seat menu (an empty seat too: Button here)
     seat_player     seat, stack (text), name                         an empty seat
     set_stack       seat, text                                       seat menu (hero without chips: his re-entry)
     set_stacks      stacks: {"2": "12.5k", "3": ""}                  the all-stacks sheet (blank keeps)
     rename          seat, name                                       seat menu
     set_type        seat, type                                       seat menu
     note            seat, text                                       seat menu
     set_status      seat, status: active | away                      seat menu
     bust, clear_seat  seat                                           seat menu
     deal                                                             New hand, Next hand
     set_cards       slot: hero | flop | turn | river, text,          the card picker ("AhKd", "AKs", "Ks7d2c", "Th")
                     replace: true when hero's cards are changed on purpose
     act             seat, kind: fold | check | call | bet | raise | allin,
                     to (a number from a preset or from Follow, text from the amount field),
                     via: "follow" when the Follow button sent it     the action bar
     close_round                                                      Rest fold, Skip the board
     edit_event      index, to (text), or kind: call | raise          a selected event on the hand line (kind: a fold
                                                                      nobody typed becomes the forgotten call or raise)
     remove_event    index                                            a selected event on the hand line
     award           ranking: [[seat], [seat, seat]]                  the result bar (Split: the ticked players as one
                                                                      tier), the seat menu
     skip_hand, discard_hand                                          the bars, table tools
     new_session     mode, and the fields of the form beside it:      first run, New tournament
                     size, level, start_stack, hero_stack, entrants,
                     remaining, paid, buyin (text; blank = not given)
     new_game        start_stack: 300 | 500                           Spin, between hands

   UI STATE (every key is optional)
     panel        "why" | "range"        which advice tab shows where only one fits
     sheet        null | "settings" | "why" | "keys" | "history" | "new" | "stacks"
     seatMenu     null | seat number      the seat whose menu is open
     menu         null | "table" | "newtable"     the table tools menu; the New table menu
     picker       null | {slot, cards: [], rank: null, rank2: null, replace}    the card picker and how far it is;
                  replace: the user chose to change hero's cards (a click on them), so another hand may
                  take the place of the class on record (set_cards then carries replace: true)
     pickerOff    true once the user closed the picker himself: the controller then does not reopen it
                  by itself until the table asks for other cards
     amount       null | {kind: "bet" | "raise", seat, to, plain}      the amount row is open (to: the chips it starts with)
     selected     null | index of the selected event on the hand line
     edit         null | "level" | "remaining" | "paid" | "avg_stack"  the strip value being typed
     target       null | seat             record the next action for this seat, not view.hand.target
     turn         null | "hand:street"    the user records the players in turn with the plain keys: until the
                                          turn reaches hero the bar is for the next player to act, not for hero
     editing      null | index            the selected event whose amount field is open
     split        null | [seat, ...]      a split pot is being ticked together (three or more at a showdown)
     awardTiers   [[seat], ...]           winners already chosen when a side pot needs another
     setupMode    "tournament" | "spin" | "aof"    the form shown on first run
     toast        {text, fix, undo, action: {label, send}} | null     shown instead of view.toast; null hides both
     fieldError   {fk, text, fix, value} | null    a value the server refused: drawn under the open field
                                                   with that data-fk, and the field is marked
     menuByKey    true when the seat menu was opened by its digit (the controller keeps it)
     newTable     {size, button}          what is chosen in the New table menu (ui.menu "newtable")
     handOpen     hand number             the hand whose text is open in the history sheet
     viewError    {message, fix, down}    the program could not show the table (or does not answer): drawn
                                          in place of the table, never as the first-run form

   EXTRAS THE PAGE UNDERSTANDS (none is required; they are not in the SPEC's view)
     view.first_run                  true: draw the first-run form, not the table
     view.setup                      {size, start_stack, level, ...}: values for the first-run form
     view.settings.ladders, .ladder  [{name, label}] and the name in use: the ladder choice in the settings
     view.settings.levels            [[sb, bb, ante], ...]: the ladder in use, shown ready to be edited
     view.settings.size_limits       [low, high]: the smallest and biggest table of this mode
     view.settings.keys              the key map of defaults.py, {table, seat, type}: the list shown by "?"
     view.strip.payouts              prizes from first place down (a list), shown the way they are typed
     view.strip.game.over            Spin: "won" or "lost" once the game is over: the bar offers a new game
     view.strip.level.due            true: the "+" of the blinds turns yellow and blinks
     view.hand.result.text           one line for the slab once the hand is settled
     view.hand.positions, .button    {seat: name} and the button seat of the hand on screen: a finished hand
                                     keeps them on the pods until the next deal
     view.hand.want_suits            {hand: "AKs", options: [["Ah","Kh"], ...]}: the exact holdings to pick from
     view.hand.before_target         the seats in front of the target that have not acted, in order
     view.hero_out                   true: hero has no chips and no hand of his is running
     view.settings.button_rule       "dead" | "forward": how the dealer button moves after a hand
     seat.status "busted"            a seat with no chips: drawn grey with the word "Out"
   ========================================================================================== */
(function () {
  "use strict";

  /* ---------- 1. Fixed lists ---------- */

  // Where each seat sits. Hero first, then clockwise. The letter is the edge of the table box
  // the pod sits against (Bottom, Left, Top, Right); the number is its centre along that edge, in percent.
  const SLOTS = {
    2: [["B", 50], ["T", 50]],
    3: [["B", 50], ["T", 25], ["T", 75]],
    4: [["B", 50], ["L", 46], ["T", 50], ["R", 46]],
    5: [["B", 50], ["L", 58], ["T", 28], ["T", 72], ["R", 58]],
    6: [["B", 50], ["L", 66], ["L", 34], ["T", 50], ["R", 34], ["R", 66]],
    7: [["B", 50], ["L", 66], ["L", 35], ["T", 35], ["T", 65], ["R", 35], ["R", 66]],
    8: [["B", 50], ["B", 11], ["L", 52], ["T", 22], ["T", 50], ["T", 78], ["R", 52], ["B", 89]],
    9: [["B", 50], ["B", 11], ["L", 57], ["L", 34], ["T", 35], ["T", 65], ["R", 34], ["R", 57], ["B", 89]],
  };

  const MODES = [
    {id: "tournament", label: "Tournament"},
    {id: "spin", label: "Spin & Gold"},
    {id: "aof", label: "All-In or Fold"},
  ];

  // The values the settings send. Change a value here if the server names it differently.
  const CHOICES = {
    style: [
      {value: "cash", label: "Cash first"},
      {value: "survive", label: "Survive, then win"},
      {value: "maxev", label: "Max EV"},
    ],
    plan: [
      {value: "full", label: "All moves"},
      {value: "allin", label: "All-in or fold only"},
    ],
    opponents: {
      tournament: [{value: "unknown", label: "Unknown"}, {value: "loose", label: "Loose"}, {value: "tight", label: "Tight"}],
      spin: [{value: "solid", label: "Solid"}, {value: "loose", label: "Loose"}, {value: "very-loose", label: "Very loose"}],
      aof: [{value: "solid", label: "Solid"}, {value: "loose", label: "Loose"}, {value: "very-loose", label: "Very loose"}],
    },
    ante_kind: [
      {value: "none", label: "None"},
      {value: "player", label: "Every player"},
      {value: "bb", label: "Big blind"},
    ],
    unit: [{value: "chips", label: "Chips"}, {value: "bb", label: "Big blinds"}],
    deck: [{value: "one-ink", label: "Two colours"}, {value: "four-colour", label: "Four colours"}],
    button_rule: [{value: "dead", label: "Dead button"}, {value: "forward", label: "Forward-moving button"}],
    type: ["unknown", "nit", "tight", "tag", "lag", "loose", "station", "maniac"],
  };

  // The list shown by "?" is drawn from the key map the server sends (view.settings.keys, written
  // in defaults.py), so it always says what the keys really do. These rows are the keys that are
  // not in that map: the seat digits and the card keys.
  const CARD_KEYS = [
    [["a k s"], "Your two cards as a class: A K S is ace-king suited. Also A K O (offsuit) and 7 7"],
    [["a h k d"], "Your two cards exactly: rank, suit, rank, suit. Suits: S spades, H hearts, D diamonds, C clubs"],
    [["k s 7 d 2 c"], "The flop. The turn and the river: one rank and one suit. T is the ten"],
    [["h"], "Once the flop is out and your hand was typed as a class: only its suits (H for both cards of A K S, H D for A K O)"],
    [["Backspace"], "Back one step; with nothing typed: undo"],
    [["Enter"], "Skip the board (when the action is not on you)"],
    [["Escape"], "Leave the cards"],
  ];
  const SEAT_DIGIT_KEYS = [
    [["1", "9"], "A seat, counted clockwise from you (you are 1): its menu opens, and the next key is for that player. " +
                 "In All-In or Fold, during a hand, the digit alone is that player's all-in (again takes it back). " +
                 "While a split pot is ticked together (Shift+W with three or more players), the digit ticks that player"],
  ];
  // How a key of the map is written on a keycap.
  const KEY_WORDS = {ArrowLeft: "Left", ArrowRight: "Right", Escape: "Esc", Delete: "Del"};

  const RANKS = "AKQJT98765432";
  const SUITS = "shdc";
  const RANK_WORD = {A: "ace", K: "king", Q: "queen", J: "jack", T: "ten", 9: "nine", 8: "eight", 7: "seven",
                     6: "six", 5: "five", 4: "four", 3: "three", 2: "two"};
  const SUIT_WORD = {s: "spades", h: "hearts", d: "diamonds", c: "clubs"};
  const MINUS = "\u2212";      // the real minus sign: both fonts have it

  // Opening one menu closes the others.
  const ALL_CLOSED = {seatMenu: null, menu: null, picker: null, amount: null, selected: null, editing: null, edit: null,
                      split: null, fieldError: null};
  function only(patch) { return Object.assign({}, ALL_CLOSED, patch); }
  // After an action is recorded the bar goes back to the server's next player.
  const AFTER_ACT = {amount: null, target: null, seatMenu: null, selected: null, editing: null};

  /* ---------- 2. Small helpers ---------- */

  function esc(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  // What a control sends when it is used: `<button${emit({op: "deal"})}>`.
  function emit(detail) { return ` data-emit="${esc(JSON.stringify(detail))}"`; }

  function list(items, draw) { return (items || []).map(draw).join(""); }

  function icon(name) { return `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><use href="#icon-${name}"/></svg>`; }

  function keycap(text) { return `<kbd>${esc(text)}</kbd>`; }

  // A value the server refused is said under the field it was typed into, and that field is marked.
  function isBad(ui, fk) { return !!(ui && ui.fieldError && ui.fieldError.fk === fk); }
  function badAttr(ui, fk) { return isBad(ui, fk) ? ' aria-invalid="true"' : ""; }
  function fieldErrorHtml(ui, fks) {
    const error = ui && ui.fieldError;
    if (!error || fks.indexOf(error.fk) < 0) return "";
    return `<p class="field-error" role="alert">${esc(error.text)}${error.fix ? `<small>${esc(error.fix)}</small>` : ""}</p>`;
  }

  /* Numbers. */

  function commas(n) { return String(Math.round(Math.abs(n))).replace(/\B(?=(\d{3})+$)/g, ","); }
  function dropZeros(text) { return text.indexOf(".") < 0 ? text : text.replace(/\.?0+$/, ""); }

  // 12900 -> "12,900"
  function fmtChips(n) {
    if (n == null) return "?";
    return (n < 0 ? MINUS : "") + commas(n);
  }
  // 5640 -> "5,640", 31260 -> "31.3k", 1250000 -> "1.25M": for small places.
  function fmtShort(n) {
    if (n == null) return "?";
    const a = Math.abs(n);
    const sign = n < 0 ? MINUS : "";
    if (a < 10000) return sign + commas(a);
    if (a < 999500) return sign + dropZeros((a / 1e3).toFixed(a < 99950 ? 1 : 0)) + "k";
    if (a < 999500000) return sign + dropZeros((a / 1e6).toFixed(a < 9995000 ? 2 : 1)) + "M";
    return sign + dropZeros((a / 1e9).toFixed(2)) + "B";
  }
  // Stacks: exact up to 999,999, short from a million.
  function fmtStack(n) { return n != null && Math.abs(n) >= 1e6 ? fmtShort(n) : fmtChips(n); }
  // Big blinds. A stack keeps its decimal ("8.0"), a bet drops it ("1bb").
  function fmtBb(x, keepZero) {
    if (x == null) return "?";
    const a = Math.abs(x);
    const sign = x < 0 ? MINUS : "";
    if (a >= 100) return sign + commas(a);
    const text = a.toFixed(1);
    return sign + (keepZero ? text : dropZeros(text));
  }
  function plus(n, text) { return (n > 0 ? "+" : "") + text; }

  // In All-In or Fold every amount in the view already is in big blinds.
  function isAof(view) { return view.mode === "aof"; }
  function showsBb(view) { return isAof(view) || view.unit === "bb"; }
  function bigBlind(view) {
    const level = view.strip && view.strip.level;
    return level && level.bb ? level.bb : null;
  }

  // An amount in the unit the user chose, and the same amount in the other unit ("" if unknown).
  function mainText(view, chips, bb, short) {
    if (isAof(view)) return fmtBb(chips) + "bb";
    if (view.unit === "bb") return fmtBb(bb) + "bb";
    return short ? fmtShort(chips) : fmtStack(chips);
  }
  function otherText(view, chips, bb) {
    if (isAof(view)) return "";
    if (view.unit === "bb") return chips == null ? "" : fmtShort(chips);
    return bb == null ? "" : fmtBb(bb) + "bb";
  }
  // An amount for which the view carries chips only (a result, a pot share).
  function chipsOnlyText(view, chips, short) {
    if (isAof(view)) return fmtBb(chips) + "bb";
    const bb = bigBlind(view);
    if (view.unit === "bb" && bb) return fmtBb(chips / bb) + "bb";
    return short ? fmtShort(chips) : fmtStack(chips);
  }
  // What goes into an amount field: digits only, so it can be edited. While the numbers are shown in
  // big blinds the fields are in big blinds too ("33.2"), and a bare number typed there is big blinds.
  function typesBb(view) { return !isAof(view) && view.unit === "bb" && !!bigBlind(view); }
  function plainAmount(view, chips) {
    if (chips == null) return "";
    if (isAof(view)) return fmtBb(chips);
    if (typesBb(view)) return dropZeros((chips / bigBlind(view)).toFixed(1));
    return String(chips);
  }
  // The attributes of an amount field. In big blinds the field also carries the exact chips it was
  // filled with: a value nobody touched is sent as it was, not rounded to a tenth of a big blind.
  function amountAttrs(view, chips) {
    if (!typesBb(view)) return "";
    const exact = chips != null ? ` data-exact="${esc(chips)}" data-exact-text="${esc(plainAmount(view, chips))}"` : "";
    return ` data-unit="bb"${exact}`;
  }
  function unitMark(view) { return typesBb(view) ? '<span class="unit">bb</span>' : ""; }
  // An <input> for an amount, filled with `chips` in the unit on screen.
  function amountInput(view, opts) {
    return `<input name="${opts.name}" value="${esc(plainAmount(view, opts.chips))}" inputmode="decimal" autocomplete="off" spellcheck="false"
      data-fk="${esc(opts.fk)}"${opts.focus ? " data-autofocus" : ""}${opts.bad ? ' aria-invalid="true"' : ""}${opts.label ? ` aria-label="${esc(opts.label)}"` : ""}` +
      `${opts.placeholder ? ` placeholder="${esc(opts.placeholder)}"` : ""}${amountAttrs(view, opts.chips)}>${unitMark(view)}`;
  }

  /* Cards. */

  function isCard(code) { return typeof code === "string" && code.length === 2 && RANKS.indexOf(code[0]) >= 0 && SUITS.indexOf(code[1]) >= 0; }
  function rankText(rank) { return rank === "T" ? "10" : rank; }
  function cardWords(code) { return isCard(code) ? `${RANK_WORD[code[0]]} of ${SUIT_WORD[code[1]]}` : String(code); }
  function splitCards(text) { return String(text || "").match(/[2-9TJQKA][shdc]/g) || []; }

  // Hearts and diamonds are outlines, spades and clubs solid: four suits in one ink.
  function suitSvg(suit) {
    const open = suit === "h" || suit === "d" ? " open" : "";
    return `<svg class="suit${open}" viewBox="0 0 24 24" aria-hidden="true"><use href="#suit-${suit}"/></svg>`;
  }
  function cardHtml(code, big) {
    return `<span class="card ${code[1]}${big ? " big" : ""}"><b>${rankText(code[0])}</b>${suitSvg(code[1])}</span>`;
  }
  // A card known by rank only: half of a hand typed as a class (AKs).
  function rankCardHtml(rank, mark, big) {
    return `<span class="card${big ? " big" : ""}"><b>${rankText(rank)}</b><span class="so">${esc(mark)}</span></span>`;
  }
  function slotHtml(now, big) { return `<span class="card slot${now ? " now" : ""}${big ? " big" : ""}"></span>`; }

  // Cards inside a line of text: "AhKd" becomes A, a heart, K, a diamond.
  function cardsInline(text) {
    const cards = splitCards(text);
    const drawn = list(cards, (code) => rankText(code[0]) + suitSvg(code[1]));
    return `<span class="txt" role="img" aria-label="${esc(cards.map(cardWords).join(", "))}">${drawn}</span>`;
  }
  // A sentence that may contain cards. Only runs of two or more are drawn, so the word "As" stays a word.
  function prose(text) {
    return esc(text).replace(/\b(?:[2-9TJQKA][shdc]){2,}\b/g, (run) => cardsInline(run));
  }

  /* Seats. */

  function seatOf(view, number) {
    return (view.table.seats || []).find((seat) => seat.seat === number) || null;
  }
  function seatName(seat) {
    if (seat.is_hero) return "You";
    return seat.name || `Seat ${seat.seat}`;
  }
  function seatTitle(seat) { return [seat.pos, seatName(seat)].filter(Boolean).join(" \u00b7 "); }

  // The betting round on screen, as a word: "12:flop".
  function roundKey(view) { return view.hand ? view.hand.no + ":" + view.hand.phase : ""; }

  /* The seat the action bar and the plain keys record for:
       the one the user aimed at (a click on a seat, a seat digit); else,
       while the user records the players in turn (ui.turn), the next player to act; else
       the server's target: hero whenever he still owes a decision (the players in front of him then
       take the passive default), otherwise the next player. */
  function actingSeat(view, ui) {
    const hand = view.hand;
    if (!hand || hand.needs !== "action") return null;
    if (ui.target != null) return ui.target;
    const before = hand.before_target || [];
    if (ui.turn && ui.turn === roundKey(view) && before.length) return before[0];
    return hand.target;
  }
  function heroToAct(view) {
    return !!(view.hand && view.hand.needs === "action" && view.hand.target_is_hero);
  }

  /* ---------- 3. Header and strip ---------- */

  const MARK = '<svg class="mark" viewBox="0 0 40 40" role="img" aria-label="Menlo Bet"><rect width="40" height="40" rx="9" fill="#FFD60A"/>' +
               '<path d="M8 30V11l12 11 12-11v19h-5V22l-7 6.5L13 22v8z" fill="#0A0A0B"/></svg>';

  function headerHtml(view, ui, mode, can) {
    const tabs = list(MODES, (m) => {
      const on = m.id === mode;
      return `<button class="tab" role="tab" aria-selected="${on}" tabindex="${on ? 0 : -1}" data-arrow` +
             `${emit({op: "set_mode", mode: m.id, ui: {setupMode: m.id}})}>${esc(m.label)}</button>`;
    });
    return `<div class="bar">
        <div class="brand">${MARK}<span class="word">Menlo<b>.bet</b></span></div>
        <div class="tabs" role="tablist" aria-label="Game" data-arrows>${tabs}</div>
      </div>
      ${view ? stripHtml(view, ui) : ""}
      ${toolsHtml(view, can)}`;
  }

  // Undo, Redo, Menu: always in that order and each in its own place, so a second click on Undo is a
  // second undo. One that has nothing to do is drawn disabled. On the first-run form the two are drawn
  // whenever the program says a step can be taken back or made again.
  function toolsHtml(view, can) {
    can = can || {};
    const undo = `<button class="tool" aria-label="Undo" title="Undo" data-fk="undo"${can.undo ? "" : " disabled"}${emit({op: "undo"})}>${icon("undo")}</button>`;
    const redo = `<button class="tool" aria-label="Redo" title="Redo" data-fk="redo"${can.redo ? "" : " disabled"}${emit({op: "redo"})}>${icon("redo")}</button>`;
    const menu = `<button class="tool" aria-label="Settings" title="Settings" data-fk="menu"${emit({ui: only({sheet: "settings"})})}>${icon("menu")}</button>`;
    return `<div class="tools">${view || can.undo || can.redo ? undo + redo : ""}${menu}</div>`;
  }

  function stripHtml(view, ui) {
    let parts;
    if (view.mode === "spin") parts = [levelStat(view, ui), opponentsStat(view), spinTally(view)];
    else if (view.mode === "aof") parts = [aofBlinds(view), opponentsStat(view), aofTally(view)];
    // (the style stands at the head of the slab, at every width: it is not repeated here)
    else parts = [levelStat(view, ui), leftStat(view, ui), paidStat(view, ui), stagePill(view), averageStat(view, ui)];
    return `<div class="strip">${parts.join("")}</div>`;
  }

  function stepper(sign, label, detail, due) {
    return `<button class="step${due ? " due" : ""}" aria-label="${esc(label)}" title="${esc(label)}"${emit(detail)}>${sign}</button>`;
  }

  // A value in the strip: a button that shows it, or the field that replaces it while it is typed.
  function stripValue(ui, name, opts) {
    if (ui.edit === name) {
      return `<span class="editing"><input class="in${opts.short ? " short" : ""}" value="${esc(opts.typed)}" autocomplete="off" spellcheck="false"
        aria-label="${esc(opts.fieldLabel)}" data-fk="edit-${name}" data-autofocus data-name="text"${badAttr(ui, "edit-" + name)}${emit(opts.send)}>` +
        `${fieldErrorHtml(ui, ["edit-" + name])}</span>`;
    }
    return `<button class="value" aria-label="${esc(opts.label)}. Change" title="${esc(opts.label)}" data-fk="value-${name}"${emit({ui: only({edit: name})})}>
        <span class="eyebrow">${esc(opts.eyebrow)}</span>${opts.shown}</button>`;
  }
  function unset() { return '<span class="unset">Add</span>'; }

  // Blinds are written the short way once both are in thousands: 1,000 / 2,000 is "1k / 2k", 1,500 / 3,000
  // "1.5k / 3k". 800 / 1,600, 1,250 / 2,500 and 12.5k / 25k stay as they are.
  function fmtBlind(n) {
    if (n != null && n >= 1000 && n < 10000 && n % 100 === 0) return dropZeros((n / 1000).toFixed(1)) + "k";
    return fmtShort(n);
  }
  function blindsText(level) {
    if (!level || level.bb == null) return "?";
    const short = level.sb >= 1000 && level.sb % 100 === 0 && level.bb % 100 === 0 ? fmtBlind : fmtShort;
    return `${short(level.sb)} / ${short(level.bb)}`;
  }
  function anteText(level) {
    if (!level || !level.ante || level.ante_kind === "none") return "no ante";
    return level.ante_kind === "bb" ? `BB ante ${fmtBlind(level.ante)}` : `ante ${fmtBlind(level.ante)}`;
  }
  // What the user would type to get the current blinds.
  function typedLevel(level) {
    if (!level || level.bb == null) return "";
    const parts = [level.sb, level.bb];
    if (level.ante) parts.push(level.ante);
    return parts.join("/");
  }

  function levelStat(view, ui) {
    const level = view.strip.level || {};
    const waiting = level.pending ? `next hand ${blindsText(level.pending)}` : anteText(level);
    const value = stripValue(ui, "level", {
      eyebrow: level.number != null ? `Level ${level.number}` : "Blinds",
      shown: `<span class="row"><span class="num v">${blindsText(level)}</span><small>${esc(waiting)}</small></span>`,
      label: `Blinds ${blindsText(level)}, ${anteText(level)}`,
      typed: typedLevel(level),
      fieldLabel: "Blinds: small blind / big blind / ante",
      send: {op: "set_level", ui: {edit: null}},
    });
    return `<div class="stat level">${stepper(MINUS, "Blinds down", {op: "level_down"})}${value}` +
           `${stepper("+", "Blinds up", {op: "level_up"}, level.due)}</div>`;
  }

  function leftStat(view, ui) {
    const left = view.strip.remaining;
    const value = stripValue(ui, "remaining", {
      eyebrow: "Left", short: true,
      shown: left == null ? unset() : `<span class="num v">${fmtChips(left)}</span>`,
      label: left == null ? "Players left: not set" : `${fmtChips(left)} players left`,
      typed: left == null ? "" : String(left),
      fieldLabel: "Players left",
      send: {op: "remaining", ui: {edit: null}},
    });
    return `<div class="stat">${stepper(MINUS, "One player fewer", {op: "remaining", step: -1})}${value}` +
           `${stepper("+", "One player more", {op: "remaining", step: 1})}</div>`;
  }

  function paidStat(view, ui) {
    const paid = view.strip.paid;
    return `<div class="stat paid">` + stripValue(ui, "paid", {
      eyebrow: "Paid", short: true,
      shown: paid == null ? unset() : `<span class="num v">${fmtChips(paid)}</span>`,
      label: paid == null ? "Places paid: not set" : `${fmtChips(paid)} places paid`,
      typed: paid == null ? "" : String(paid),
      fieldLabel: "Places paid",
      send: {op: "set_tournament", field: "paid", ui: {edit: null}},
    }) + `</div>`;
  }

  // Near the money the pill is outlined, on the bubble it is yellow, in the money green.
  const STAGE_LOOK = {approach: "near", bubble: "bubble", itm: "money", final: "money"};
  function stagePill(view) {
    const stage = view.strip.stage;
    if (!stage || !stage.label) return "";
    return `<span class="pill stage ${STAGE_LOOK[stage.code] || ""}" title="${esc(stage.label)}">${esc(stage.label)}</span>`;
  }

  function averageStat(view, ui) {
    const avg = view.strip.avg_stack;
    const inBb = view.strip.avg_bb != null ? `<small>${fmtBb(view.strip.avg_bb)}bb</small>` : "";
    return `<div class="stat from-avg">` + stripValue(ui, "avg_stack", {
      eyebrow: "Average",
      shown: avg == null ? unset() : `<span class="row"><span class="num v">${fmtShort(avg)}</span>${inBb}</span>`,
      label: avg == null ? "Average stack: not set" : `Average stack ${fmtChips(avg)}`,
      typed: avg == null ? "" : String(avg),
      fieldLabel: "Average stack",
      send: {op: "set_tournament", field: "avg_stack", ui: {edit: null}},
    }) + `</div>`;
  }

  // The rule that moves the dealer button after a hand ("dead" unless the view says otherwise).
  function buttonRule(view) {
    return (view.settings && view.settings.button_rule) || (view.strip && view.strip.button_rule) || "dead";
  }

  function labelOf(choices, value) {
    const found = choices.find((choice) => choice.value === value);
    return found ? found.label : String(value || "");
  }
  function nextOf(choices, value) {
    const at = choices.findIndex((choice) => choice.value === value);
    return choices[(at + 1) % choices.length].value;
  }

  // A row of either-or buttons. `send` turns a value into the event it sends.
  function choiceHtml(label, choices, current, send) {
    const buttons = list(choices, (choice) =>
      `<button class="tab" role="radio" aria-checked="${choice.value === current}"${emit(send(choice.value))}>${esc(choice.label)}</button>`);
    return `<div class="tabs" role="radiogroup" aria-label="${esc(label)}">${buttons}</div>`;
  }

  function opponentsStat(view) {
    const choices = CHOICES.opponents[view.mode] || CHOICES.opponents.tournament;
    return `<div class="stat">` + choiceHtml("Opponents", choices, view.strip.opponents,
      (value) => ({op: "set_config", key: "opponents", value: value})) + `</div>`;
  }

  function plainStat(eyebrow, shown, extra) {
    return `<div class="stat ${extra || ""}"><div class="value"><span class="eyebrow">${esc(eyebrow)}</span>${shown}</div></div>`;
  }

  function spinTally(view) {
    const tally = view.strip.tally;
    if (!tally) return "";
    const games = tally.games || 0;
    const wins = tally.wins || 0;
    // A spin breaks even at 35.9% of games won.
    const rate = games ? `<span class="row"><span class="num v">${(100 * wins / games).toFixed(1)}%</span><small>35.9% breaks even</small></span>` : "";
    return plainStat("Games", `<span class="num v">${fmtChips(games)}</span>`) +
           plainStat("Won", `<span class="num v">${fmtChips(wins)}</span>`) +
           (rate ? plainStat("Win rate", rate, "from-style") : "");
  }

  function aofBlinds(view) {
    const level = view.strip.level || {};
    const blinds = level.bb != null ? `${fmtBb(level.sb)} / ${fmtBb(level.bb)}` : "0.5 / 1";
    return plainStat("Blinds", `<span class="row"><span class="num v">${blinds}</span><small>8bb cap</small></span>`);
  }

  function aofTally(view) {
    const tally = view.strip.tally;
    if (!tally || tally.net_bb == null) return "";
    const net = tally.net_bb;
    const look = net > 0 ? " win" : net < 0 ? " loss" : "";
    return plainStat("Session", `<span class="num v${look}">${plus(net, fmtBb(net))}bb</span>`);
  }

  /* ---------- 4. Advice ---------- */

  // The answer on screen is the coach's answer for exactly this table.
  function isCurrent(view, advice) {
    return !!(advice && advice.status === "ready" && advice.rev === view.rev && advice.headline);
  }

  // What the slab says when there is nothing to advise: what the table is waiting for.
  function waitingFor(view) {
    const hand = view.hand;
    const result = hand && hand.result && hand.result.text ? hand.result.text + ". " : "";
    if (spinOver(view) && (!hand || hand.needs === "next")) {
      return {verb: view.strip.game.over === "won" ? "Game won" : "Game over", text: result + "Press N for a new game."};
    }
    // No chips on hero's seat: what he can do stays on the slab (a hand dealt now would be dealt without him).
    if (heroOutOfChips(view)) {
      const again = view.mode === "tournament" ? "tournament" : "game";
      return {verb: "You are out", own: true,
              text: `${result}Type a new stack on your seat to re-enter (S), or start a new ${again} from the settings.`};
    }
    if (!hand) return {verb: "New hand", text: "Press N, then type your two cards: A K S."};
    if (hand.needs === "cards") return {verb: "Your cards", text: "Type your two cards: A K S, or A H K D."};
    if (hand.needs === "board") {
      const count = (hand.board || []).length;
      if (count < 3) return {verb: "Flop", text: "Type the three cards: K S 7 D 2 C."};
      return {verb: count === 3 ? "Turn" : "River", text: "Type the card: T H."};
    }
    if (hand.needs === "result") return {verb: "Who won?", text: "W if you won, L if you lost, or click the winner."};
    if (hand.needs === "next") return {verb: "Hand over", text: result + "Press N for the next hand."};
    const seat = seatOf(view, hand.target);
    if (seat && !seat.is_hero) return {verb: "Wait", text: `${seatTitle(seat)} has not acted yet.`};
    return {verb: "Wait", text: ""};
  }

  // One object for the slab, whatever the state.
  function slabContent(view, advice, ui) {
    if (isCurrent(view, advice)) {
      const h = advice.headline;
      // While the players in front of hero are still being recorded in turn, the answer is for the
      // spot as it will be if they all fold: the slab says so.
      const eyebrow = !heroToAct(view) ? "Coach" : actingSeat(view, ui) === view.hand.target ? "Your turn" : "If they fold";
      return {tone: h.tone || "wait", eyebrow: eyebrow, verb: h.verb, size: h.size_text,
              qualifier: h.qualifier, spot: advice.spot, sure: h.sure, live: true};
    }
    const fresh = advice && advice.rev === view.rev && advice.status === "none";
    if (heroToAct(view) && !fresh) {
      // A new answer is on its way. The old one stays readable but never wears yellow.
      const old = advice && advice.headline;
      return {tone: "wait", eyebrow: old ? "Updating" : "Coach", verb: old ? old.verb : "Updating",
              size: old ? old.size_text : "", spot: old ? advice.spot : "The coach is working on this spot.", live: false};
    }
    const waiting = waitingFor(view);
    // Hero is sitting out: the slab says so, and which key ends it.
    const hero = heroSeat(view);
    if (hero && hero.status === "away") {
      const then = waiting.verb === "Wait" ? "" : " " + waiting.text;
      return {tone: "wait", eyebrow: "Coach", verb: "Sitting out", spot: "You are sitting out: press O to sit back in." + then, live: false};
    }
    // Once the hand is settled the slab says who won what; otherwise the coach's own line on what it waits for.
    const settled = !!(view.hand && view.hand.needs === "next");
    const spot = settled || waiting.own ? waiting.text : (fresh && advice.spot) || waiting.text;
    return {tone: "wait", eyebrow: "Coach", verb: waiting.verb, spot: spot, live: false};
  }

  // Long verbs get a smaller size so they stay on the slab. The longest answer of two words
  // ("RE-RAISE ALL-IN") is written word under word where the slab is a narrow column (from 1024),
  // so it keeps a size that still reads as the answer.
  function verbClass(verb, live) {
    const text = String(verb || "");
    if (text.length >= 10) return live && text.length >= 12 && text.split(" ").length === 2 ? " xlong two" : " xlong";
    return text.length >= 8 ? " long" : "";
  }
  function verbHtml(verb, live) {
    const cls = verbClass(verb, live);
    const words = cls.indexOf(" two") >= 0 ? String(verb).split(" ").map((word) => `<span>${esc(word)}</span>`).join(" ") : esc(verb);
    return `<span class="verb${cls}">${words}</span>`;
  }
  // The size as the coach writes it, "TO 2BB · 1,200": the second unit is marked, so the narrow slab can
  // leave it out when a pill needs the room.
  function sizeHtml(size) {
    const text = String(size);
    const at = text.indexOf(" \u00b7 ");
    if (at < 0) return `<span class="size">${esc(text)}</span>`;
    return `<span class="size">${esc(text.slice(0, at))}<span class="also">${esc(text.slice(at))}</span></span>`;
  }

  // How sure: three bars filled is clear, two standard, one close.
  const SURE_BARS = {clear: 3, standard: 2, close: 1};
  function sureHtml(sure) {
    const filled = SURE_BARS[sure];
    if (!filled) return "";
    const bars = [1, 2, 3].map((n) => `<i${n <= filled ? ' class="on"' : ""}></i>`).join("");
    // ("close" alone at the top right of a box reads as a close button)
    return `<span class="sure eyebrow"><span class="pips" aria-hidden="true">${bars}</span>${esc(sure === "close" ? "close spot" : sure)}</span>`;
  }

  // What the answers depend on besides the table: the style and the moves, and re-entry and bounty while
  // they are on. In sight at every width, at the head of the slab; a click opens the settings.
  const MOVES_WORDS = {full: "All moves", allin: "All-in or fold only"};      // (the labels of CHOICES.plan)
  function coachMode(view) {
    if (view.mode !== "tournament") return "";
    const strip = view.strip || {};
    const words = [labelOf(CHOICES.style, strip.style), MOVES_WORDS[strip.plan] || labelOf(CHOICES.plan, strip.plan)];
    if (strip.reentry_open) words.push("Re-entry open");
    if (strip.bounty) words.push("Bounty");
    return words.filter(Boolean).join(" \u00b7 ");
  }

  function slabHtml(content, mode) {
    const how = mode ? `<button class="mode" data-fk="coach-mode" title="${esc("Style and moves: " + mode + ". Change them in the settings")}"` +
                       ` aria-label="${esc("Style and moves: " + mode + ". Open the settings")}"${emit({ui: only({sheet: "settings"})})}>${esc(mode)}</button>` : "";
    return `<div class="slab ${esc(content.tone)}${content.qualifier ? " has-pill" : ""}">
      <div class="head"><span class="eyebrow">${esc(content.eyebrow)}</span>${how}${content.live ? sureHtml(content.sure) : ""}</div>
      <div class="act">${verbHtml(content.verb, content.live && content.tone !== "wait")}
        ${content.size ? sizeHtml(content.size) : ""}
        ${content.qualifier ? `<span class="pill" title="${esc(content.qualifier)}">${esc(content.qualifier)}</span>` : ""}</div>
      ${content.spot ? `<div class="spot" title="${esc(content.spot)}">${prose(content.spot)}</div>` : ""}
    </div>`;
  }

  function tileHtml(tile) {
    const look = tile.sign > 0 ? " win" : tile.sign < 0 ? " loss" : "";
    const length = String(tile.value || "").length;
    const fit = length > 11 ? " xlong" : length > 7 ? " long" : "";
    // A value made of words ("pocket pair below top card") gets the whole row and may take two lines.
    const words = length > 11 && /[a-z]{3}/i.test(String(tile.value));
    return `<div class="tile${words ? " wide" : ""}"><div class="eyebrow">${esc(tile.label)}</div>
      <div class="num${look}${fit}">${esc(tile.value)}</div>
      ${tile.note ? `<div class="sub">${esc(tile.note)}</div>` : ""}</div>`;
  }

  function groupHtml(title, lines) {
    if (!lines || !lines.length) return "";
    return `<div class="group"><div class="eyebrow">${esc(title)}</div><ul>${list(lines, (line) => `<li>${prose(line)}</li>`)}</ul></div>`;
  }

  // The reasons: one sentence, the key numbers, what flips the answer, then plans and warnings.
  // While no answer is live only the warnings are shown.
  function whyHtml(advice, live) {
    if (!advice) return "";
    const parts = [];
    if (live) {
      if (advice.reason) parts.push(`<p class="reason">${prose(advice.reason)}</p>`);
      if (advice.tiles && advice.tiles.length) parts.push(`<div class="tiles">${list(advice.tiles, tileHtml)}</div>`);
      if (advice.flip) parts.push(`<p>${prose(advice.flip)}</p>`);
      if (advice.also) parts.push(groupHtml("Also fine", [advice.also]));
      parts.push(groupHtml("Plan", advice.plans));
    }
    parts.push(groupHtml("Watch out", (advice.warnings || []).map((warning) => warning.text)));
    if (live && advice.source) parts.push(`<div class="source">${esc(advice.source)}</div>`);
    const html = parts.join("");
    return html ? `<div class="panel why">${html}</div>` : "";
  }

  // Where the tournament stands: the stage, the gear for this stack, the fold clock.
  function contextHtml(advice) {
    const context = (advice && advice.context) || {};
    const rows = [["Stage", context.stage], ["Gear", context.gear], ["Fold clock", context.fold_clock]].filter((row) => row[1]);
    if (!rows.length) return "";
    return `<div class="panel where"><dl class="context">` +
           list(rows, (row) => `<dt class="eyebrow">${row[0]}</dt><dd>${prose(row[1])}</dd>`) + `</dl></div>`;
  }

  // The name of a cell: row and column run from A to 2; suited hands sit above the diagonal.
  function handAt(row, col) {
    if (row === col) return RANKS[row] + RANKS[col];
    return row < col ? RANKS[row] + RANKS[col] + "s" : RANKS[col] + RANKS[row] + "o";
  }

  function chartHtml(chart) {
    if (!chart || !chart.cells) return "";
    const known = {r: 1, c: 1, x: 1};
    let cells = "";
    let heroCode = "f";
    for (let row = 0; row < 13; row++) {
      for (let col = 0; col < 13; col++) {
        const hand = handAt(row, col);
        const raw = (chart.cells[row] || [])[col];
        const code = known[raw] ? raw : "f";
        const mine = hand === chart.hero;
        if (mine) heroCode = code;
        const number = chart.numbers && chart.numbers[row] ? chart.numbers[row][col] : null;
        const tip = number != null && number !== "" ? ` title="${esc(hand + ": " + number)}"` : "";
        cells += `<span class="cell ${code}${mine ? " me" : ""}"${tip}>${hand}</span>`;
      }
    }
    const legend = chart.legend || [];
    const heroLabel = (legend.find((item) => item.code === heroCode) || {label: "fold"}).label;
    const summary = `Range chart: ${chart.title || ""}. ${chart.share != null ? chart.share + "% of hands. " : ""}` +
                    (chart.hero ? `Your hand ${chart.hero}: ${heroLabel}.` : "");
    return `<div class="panel chart">
      <div class="head"><span class="eyebrow">${esc(chart.title || "Range")}</span>
        ${chart.share != null ? `<span class="eyebrow">${esc(chart.share)}% of hands</span>` : ""}</div>
      <div class="grid13" role="img" aria-label="${esc(summary)}">${cells}</div>
      <div class="legend">${list(legend, (item) => `<span><i class="${known[item.code] ? item.code : "f"}"></i>${esc(item.label)}</span>`)}
        ${chart.hero ? `<span><i class="me"></i>${esc(chart.hero)}, your hand</span>` : ""}</div>
    </div>`;
  }

  function adviceHtml(view, advice, ui) {
    const content = slabContent(view, advice, ui);
    const where = contextHtml(advice);
    const why = whyHtml(advice, content.live);
    const chart = content.live ? chartHtml(advice.chart) : "";
    // Narrow screens: one line that opens the reasons and the chart as a sheet.
    const firstLine = content.live ? advice.reason : ((advice && advice.context && (advice.context.fold_clock || advice.context.stage)) || "");
    // The row is kept even when there is nothing to open, so the table below never moves (a toast also lands on it).
    const whyline = why || chart || where
      ? `<button class="whyline"${emit({ui: only({sheet: "why"})})}><span class="text">${prose(firstLine || "The reasons")}</span>` +
        `<span class="more">${chart ? "Why and range" : "Why"}${icon("chevron")}</span></button>`
      : `<div class="whyline"></div>`;
    let panel = ui.panel === "range" ? "range" : "why";
    if (!chart) panel = "why";
    const tabs = (why || where) && chart
      ? `<div class="tabs advice-tabs" role="tablist" aria-label="Details">
          <button class="tab" role="tab" aria-selected="${panel === "why"}"${emit({ui: {panel: "why"}})}>Why</button>
          <button class="tab" role="tab" aria-selected="${panel === "range"}"${emit({ui: {panel: "range"}})}>Range</button></div>`
      : "";
    return {panel: panel, html: slabHtml(content, coachMode(view)) + whyline + tabs + why + chart + where};
  }

  /* ---------- 5. Table ---------- */

  // CSS for a pod pushed against its edge of the table box.
  function podPlace(slot, hero) {
    const side = slot[0], at = slot[1];
    const w = hero ? "var(--hero-w)" : "var(--pod-w)";
    const h = hero ? "var(--hero-h)" : "var(--pod-h)";
    if (side === "T") return `top:0;left:calc(${at}% - ${w}/2)`;
    if (side === "B") return `bottom:0;left:calc(${at}% - ${w}/2)`;
    if (side === "L") return `left:0;top:calc(${at}% - ${h}/2)`;
    return `right:0;top:calc(${at}% - ${h}/2)`;
  }
  // The bet sits 6px outside the pod, on the felt side.
  function chipPlace(slot, hero) {
    const side = slot[0], at = slot[1];
    const w = hero ? "var(--hero-w)" : "var(--pod-w)";
    const h = hero ? "var(--hero-h)" : "var(--pod-h)";
    if (side === "T") return `top:calc(${h} + 6px);left:${at}%;transform:translateX(-50%)`;
    if (side === "B") return `bottom:calc(${h} + 6px);left:${at}%;transform:translateX(-50%)`;
    if (side === "L") return `left:calc(${w} + 6px);top:${at}%;transform:translateY(-50%)`;
    return `right:calc(${w} + 6px);top:${at}%;transform:translateY(-50%)`;
  }
  // The dealer button sits on the pod corner nearest the middle of the table.
  function dealerPlace(slot, hero) {
    const side = slot[0], at = slot[1];
    const w = hero ? "var(--hero-w)" : "var(--pod-w)";
    const h = hero ? "var(--hero-h)" : "var(--pod-h)";
    const d = "var(--deal)";
    if (side === "T" || side === "B") {
      const x = `calc(${at}% ${at <= 50 ? "+" : "-"} ${w}/2 - ${d}/2)`;
      const y = side === "T" ? `top:calc(${h} - ${d}/2)` : `bottom:calc(${h} - ${d}/2)`;
      return `left:${x};${y}`;
    }
    const y = `calc(${at}% ${at < 46 ? "+" : "-"} ${h}/2 - ${d}/2)`;
    const x = side === "L" ? `left:calc(${w} - ${d}/2)` : `right:calc(${w} - ${d}/2)`;
    return `top:${y};${x}`;
  }

  /* A finished hand that is still on screen keeps the seat names and the dealer button it was played
     with (view.hand.positions, view.hand.button), so "CO wins" points at the pod called CO. The table
     already stands for the next deal (view.table.button, seat.pos); the pods switch to that at the next
     deal, or as soon as the user moves the button or changes a seat. */
  let settledSeen = null;      // the finished hand on screen, and the table as it stood when it was first drawn
  function tableSignature(view) {
    return view.table.button + "|" + (view.table.seats || []).map((seat) => seat.seat + (seat.empty ? "-" : ":" + seat.pos)).join(",");
  }
  function finishedHandNames(view) {
    const hand = view.hand;
    if (!hand || hand.needs !== "next" || !hand.positions) { settledSeen = null; return null; }
    const key = view.mode + ":" + hand.no;
    const signature = tableSignature(view);
    if (!settledSeen || settledSeen.key !== key) settledSeen = {key: key, signature: signature, moved: false};
    // The button was moved or a seat changed: from then on the next hand's names, also if it is moved back.
    if (settledSeen.signature !== signature) settledSeen.moved = true;
    if (settledSeen.moved) return null;
    return {positions: hand.positions, button: hand.button};
  }

  function tableHtml(view, ui) {
    const table = view.table;
    const slots = SLOTS[table.size] || SLOTS[9];
    const names = finishedHandNames(view);
    const button = names ? names.button : table.button;
    let pods = "", chips = "", dealer = "";
    (table.seats || []).forEach((seat) => {
      const slot = slots[seat.seat - 1];
      if (!slot) return;
      if (names) seat = Object.assign({}, seat, {pos: names.positions[seat.seat] || "", is_button: seat.seat === names.button});
      pods += podHtml(view, ui, seat, slot);
      chips += chipHtml(view, seat, slot);
      if (seat.seat === button) dealer = `<span class="deal" style="${dealerPlace(slot, seat.is_hero)}" aria-hidden="true">D</span>`;
    });
    const tools = `<button class="tool table-tools" aria-label="Table tools: dealer button, seats, stacks" title="Table tools" data-arrow tabindex="-1"` +
                  `${emit({ui: only({menu: "table"})})}>${icon("sliders")}</button>`;
    return `<div class="felt"></div>${pods}${chips}${dealer}${centreHtml(view, ui)}${tools}${tableMenus(view, ui)}`;
  }

  // What a click on a seat does: open its menu and, mid-hand, aim the action bar at that player.
  function seatClick(view, seat) {
    const midHand = view.hand && view.hand.needs === "action";
    const aim = midHand && !seat.empty && !seat.is_hero && seat.in_hand ? seat.seat : null;
    return {ui: only({seatMenu: seat.seat, target: aim})};
  }

  /* The stack of a pod: the amount in the chosen unit, and what stands with it: the same stack in the
     other unit, or the word of a player who is sitting out or has no chips left. That second part is
     drawn twice and the width shows one of the two: beside the stack from 1280, on the row under it
     in a narrower pod (see app.css). */
  function stackParts(view, seat) {
    if (seat.all_in) return {stack: '<span class="stack"><span class="num">ALL-IN</span></span>', second: ""};
    const word = {away: "Away", busted: "Out"}[seat.status];
    let number, unit = "";
    if (showsBb(view)) {
      number = fmtBb(isAof(view) ? seat.stack : seat.stack_bb, true);
      unit = "<u>bb</u>";
    } else {
      number = fmtStack(seat.stack);
    }
    if (seat.stale) number = "~" + number;      // a stack nobody has confirmed since a hand that was not recorded
    const other = otherText(view, seat.stack, seat.stack_bb);
    const second = word ? `<span class="tag">${word}</span>` : other ? `<span class="other">${other}</span>` : "";
    return {stack: `<span class="stack"><span class="num">${number}</span>${unit}${second}</span>`, second: second};
  }

  function podWords(view, seat, state) {
    const words = [`Seat ${seat.seat}`, seat.pos, seatName(seat)];
    if (seat.stack != null) words.push(isAof(view) ? `${fmtBb(seat.stack, true)} big blinds` : `${fmtChips(seat.stack)} chips`);
    if (!isAof(view) && seat.stack_bb != null) words.push(`${fmtBb(seat.stack_bb, true)} big blinds`);
    if (seat.stale) words.push("stack not confirmed");
    if (seat.type && seat.type !== "unknown") words.push(seat.type);
    if (seat.folded) words.push("folded");
    if (seat.all_in) words.push("all-in");
    if (seat.status === "away") words.push("sitting out");
    if (seat.status === "busted") words.push("no chips");
    if (seat.is_button) words.push("dealer button");
    if (state.target) words.push("next to act");
    return words.filter(Boolean).join(", ");
  }

  function podState(view, ui, seat) {
    const handOn = !!view.hand;
    const acting = actingSeat(view, ui);
    const aimed = acting != null ? seat.seat === acting : !!seat.is_target;
    const target = aimed || ui.seatMenu === seat.seat;
    // Yellow is hero's seat while the decision is his; a white ring is where the next key lands.
    const turn = seat.is_hero && aimed && heroToAct(view) && ui.target == null;
    const out = seat.folded || seat.status === "away" || seat.status === "busted" || (handOn && seat.in_hand === false);
    let cls = "pod";
    if (seat.is_hero) cls += " hero";
    if (out) cls += " out";
    if (seat.status === "away") cls += " away";
    if (seat.status === "busted") cls += " busted";
    if (seat.all_in) cls += " allin";
    if (seat.stale) cls += " stale";
    if (turn) cls += " turn";
    else if (target) cls += " target";
    return {cls: cls, target: target};
  }

  function podHtml(view, ui, seat, slot) {
    const place = podPlace(slot, !!seat.is_hero);
    if (seat.empty) {
      const on = ui.seatMenu === seat.seat ? " target" : "";
      return `<button class="pod empty${on}" style="${place}" data-seat="${seat.seat}" data-arrow tabindex="-1"
        aria-label="Seat ${seat.seat}, empty. Add a player"${emit(seatClick(view, seat))}>+ Player</button>`;
    }
    const state = podState(view, ui, seat);
    const words = podWords(view, seat, state);
    const title = seat.note ? ` title="${esc(seatName(seat) + ": " + seat.note)}"` : "";
    if (seat.is_hero) return heroPodHtml(view, ui, seat, place, state, words);
    // The type is a tag of its own, before the name: it is what changes the advice, so it is never cut.
    const type = seat.type && seat.type !== "unknown" ? `<span class="type">${esc(seat.type)}</span>` : "";
    const parts = stackParts(view, seat);
    return `<button class="${state.cls}" style="${place}" data-seat="${seat.seat}" data-arrow tabindex="-1" aria-label="${esc(words)}"${title}${emit(seatClick(view, seat))}>
      <span class="top"><span class="pos">${esc(seat.pos || "\u2013")}</span><span class="key">${seat.seat}</span></span>
      ${parts.stack}
      <span class="more">${parts.second}${type}<span class="name">${esc(seat.name || `Seat ${seat.seat}`)}</span></span>
    </button>`;
  }

  // Hero's two cards as they are known: exact, as a class (AKs), or not yet.
  function heroCardsHtml(view) {
    const hand = view.hand;
    const cards = hand && hand.hero_cards && hand.hero_cards.length === 2 ? hand.hero_cards : null;
    if (cards) return {html: cardHtml(cards[0], true) + cardHtml(cards[1], true), words: cards.map(cardWords).join(", ")};
    const cls = hand && hand.hero_class;
    if (cls) {
      const mark = cls.length === 3 ? cls[2] : "";
      return {html: rankCardHtml(cls[0], mark, true) + rankCardHtml(cls[1], mark, true), words: cls};
    }
    const now = !!hand && hand.needs === "cards";
    return {html: slotHtml(now, true) + slotHtml(now, true), words: "not set"};
  }

  function heroPodHtml(view, ui, seat, place, state, words) {
    const cards = heroCardsHtml(view);
    const parts = stackParts(view, seat);
    const pick = view.hand ? emit({ui: only({picker: freshPicker("hero", true)})}) : emit(seatClick(view, seat));
    return `<div class="${state.cls}" style="${place}" data-seat="${seat.seat}">
      <button class="hand" data-arrow tabindex="0" data-fk="hero-cards" aria-label="Your cards: ${esc(cards.words)}. Change"${pick}>${cards.html}</button>
      <button class="info" data-arrow tabindex="-1" data-fk="hero-info" aria-label="${esc(words)}"${emit(seatClick(view, seat))}>
        <span class="top"><span class="pos">${esc(seat.pos || "\u2013")}</span></span>
        ${parts.stack}
        <span class="more">${parts.second}<span class="pill you">You</span></span>
      </button>
    </div>`;
  }

  // The chips a player has in front of him; after the result, what he won or lost instead.
  function chipHtml(view, seat, slot) {
    if (seat.empty) return "";
    const place = chipPlace(slot, !!seat.is_hero);
    if (seat.delta) {
      const text = plus(seat.delta, chipsOnlyText(view, seat.delta, true));
      return `<span class="chip ${seat.delta > 0 ? "won" : "lost"}" style="${place}">${text}</span>`;
    }
    if (!seat.bet) return "";
    // Narrow tables have room for "12.9k" only; from 1280 wide the chip shows the exact bet.
    const short = mainText(view, seat.bet, seat.bet_bb, true);
    const exact = mainText(view, seat.bet, seat.bet_bb, false);
    const text = short === exact ? exact : `<span class="exact">${exact}</span><span class="short">${short}</span>`;
    return `<span class="chip${seat.all_in ? " allin" : ""}" style="${place}">${text}</span>`;
  }

  function potsText(view, pots) {
    return pots.map((pot, i) => `${i === 0 ? "Main" : "Side"} ${chipsOnlyText(view, pot.amount)}`).join(" \u00b7 ");
  }

  // The middle of the table: the pot, then the board.
  function centreHtml(view, ui) {
    const hand = view.hand;
    if (!hand) return "";
    const other = otherText(view, hand.pot, hand.pot_bb);
    const pots = hand.pots && hand.pots.length > 1 ? `<div class="pots">${esc(potsText(view, hand.pots))}</div>` : "";
    // A pot of a million or more: "2.7M" where the table is small, the exact chips from 1280 (as the bets do).
    const short = mainText(view, hand.pot, hand.pot_bb);
    const exact = isAof(view) || view.unit === "bb" ? short : fmtChips(hand.pot);
    const pot = short === exact ? exact : `<span class="exact">${exact}</span><span class="short">${short}</span>`;
    return `<div class="centre">
      <div class="pot"><span class="eyebrow">Pot</span><span class="num">${pot}</span>${other ? `<small>${other}</small>` : ""}</div>
      ${pots}${boardHtml(view)}
    </div>`;
  }

  // The flop is one button, the turn and the river one each. The street being waited for shows empty slots.
  function boardHtml(view) {
    const hand = view.hand;
    const board = hand.board || [];
    const waiting = hand.needs === "board";
    const streets = [
      {slot: "flop", name: "Flop", cards: board.slice(0, 3), size: 3, wanted: waiting && board.length < 3},
      {slot: "turn", name: "Turn", cards: board.slice(3, 4), size: 1, wanted: waiting && board.length === 3},
      {slot: "river", name: "River", cards: board.slice(4, 5), size: 1, wanted: waiting && board.length === 4},
    ];
    const html = list(streets, (street) => {
      const open = emit({ui: only({picker: freshPicker(street.slot)})});
      if (street.cards.length === street.size) {
        return `<button class="street" data-arrow tabindex="-1" data-fk="board-${street.slot}"
          aria-label="${street.name}: ${esc(street.cards.map(cardWords).join(", "))}. Change"${open}>${list(street.cards, (code) => cardHtml(code))}</button>`;
      }
      if (street.wanted) {
        const slots = new Array(street.size).fill(slotHtml(true)).join("");
        return `<button class="street" data-arrow tabindex="-1" data-fk="board-${street.slot}" aria-label="${street.name}: pick the cards"${open}>${slots}</button>`;
      }
      return "";
    });
    return html ? `<div class="board">${html}</div>` : "";
  }

  /* ---------- 6. Hand line and amount row ---------- */

  // "AhKd" and "Ks 7d 2c" are cards; "AKs" (a class) and "Hal fold" are not.
  function isCardRun(text) { return /^(?:[2-9TJQKA][shdc] ?)+$/.test(String(text || "").trim()); }

  // One chip per event: "Hal raise 2.2bb" with the action in the number face.
  function eventHtml(event, selected) {
    let inside;
    if (isCardRun(event.text)) {
      inside = `<b>${cardsInline(event.text)}</b>`;
    } else if (event.name && String(event.text).indexOf(event.name + " ") === 0) {
      inside = `${esc(event.name)} <b>${esc(event.text.slice(event.name.length + 1))}</b>`;
    } else {
      inside = `<b>${esc(event.text)}</b>`;
    }
    const cls = "ev" + (event.auto ? " auto" : "") + (selected ? " sel" : "");
    return `<span class="${cls}">${inside}</span>`;
  }

  function lineHtml(view, ui) {
    const hand = view.hand;
    if (!hand) return lastHandHtml(view);
    if (ui.amount) return amountRowHtml(view, ui);
    const events = hand.line || [];
    if (!events.length) return `<span class="hint">The hand is written here, step by step.</span>`;
    const last = events.length - 1;
    const chips = list(events, (event, at) => {
      const selected = ui.selected === event.i;
      // A click selects the step and the cursor stays on it; a second click opens its amount, or lets go of it.
      const next = !selected ? only({selected: event.i})
        : eventHasAmount(event) && ui.editing !== event.i ? {editing: event.i} : {selected: null, editing: null};
      return `<button class="evb" data-arrow tabindex="${at === last ? 0 : -1}" aria-pressed="${selected}" data-fk="event-${event.i}"` +
             `${emit({ui: next})}>${eventHtml(event, selected)}</button>`;
    });
    return `<div class="events" role="group" aria-label="This hand, step by step" data-arrows>${chips}</div>`;
  }

  // Between hands: the last hand, as a way into the history.
  function lastHandHtml(view) {
    const last = (view.history || [])[0];
    if (!last) return `<span class="hint">No hand yet.</span>`;
    const net = last.net ? ` ${plus(last.net, chipsOnlyText(view, last.net))}` : "";
    const cards = isCardRun(last.cards) ? cardsInline(last.cards) : esc(last.cards || "");
    return `<div class="events"><button class="evb" aria-label="Hand ${esc(last.no)}. Open the hand history"${emit({ui: only({sheet: "history"})})}>
      <span class="ev">Hand ${esc(last.no)} <b>${cards}</b> ${esc(last.pos || "")} <b>${esc(last.did ? didWord(last.did) : "")}${esc(net)}</b></span></button></div>`;
  }

  // The amount field with its presets. A preset is a bet of that size in one click.
  function amountRowHtml(view, ui) {
    const hand = view.hand;
    const amount = ui.amount;
    const seat = amount.seat != null ? amount.seat : hand.target;
    const forTarget = seat === hand.target;
    const legal = (forTarget && hand.legal && hand.legal[amount.kind]) || {};
    const chips = amount.to != null ? amount.to : legal.default;
    const player = seatOf(view, seat);
    // Whose bet it is stands on the action bar ("Recording"); the field only says what the number is.
    const who = player && !player.is_hero ? `${seatTitle(player)}: ` : "";
    const label = amount.kind === "bet" ? "Bet" : "Raise to";
    const presets = forTarget ? list(hand.presets, (preset) =>
      `<button type="button" class="preset"${emit({op: "act", seat: seat, kind: amount.kind, to: preset.to, ui: AFTER_ACT})}>${esc(preset.label)}</button>`) : "";
    const refused = fieldErrorHtml(ui, ["amount"]);
    return `<form class="amount" data-from="amount"${emit({op: "act", seat: seat, kind: amount.kind, plain: !!amount.plain, ui: AFTER_ACT})}>
      <label class="field${refused ? " bad" : ""}"><span class="eyebrow">${esc(label)}</span>
        ${amountInput(view, {name: "to", chips: chips, fk: "amount", focus: true, bad: !!refused, label: who + label,
                             placeholder: forTarget ? "" : "usual size"})}</label>
      ${refused || `<div class="presets">${presets}</div>`}
      <button type="submit" class="btn compact">OK ${keycap("Enter")}</button>
      <button type="button" class="tool" aria-label="Cancel" title="Cancel"${emit({ui: {amount: null}})}>${icon("close")}</button>
    </form>`;
  }

  /* ---------- 7. Action bar ---------- */

  /* The bar is two rows: one line that says what the bar is for (whose action the plain keys record),
     and the buttons. While a hand is played the buttons sit in six fixed slots, so a button never
     turns up where another one was a moment ago:
       1      the coach's button: Follow on hero's turn (drawn disabled while another player acts),
              Next hand once hero has folded or the hand is over
       2 - 5  fold, check or call, bet or raise, all-in: always for the player the first row names
       6      Rest fold (Rest check, Skip the board)
     On top of that a pointer click on a bar button that was not at that place 400 ms earlier is
     ignored (see barClickTooEarly): a double-click records one action. Keys are not affected. */

  // A button of the bar: the word with its key, and under it the amount when there is one.
  // `slot` is its place in the row of fixed slots: "1" ... "6", or a span such as "1 / 6".
  function barButton(opts) {
    const cls = "btn" + (opts.primary ? " primary" : "") + (opts.wide ? " wide" : "");
    const key = opts.key ? keycap(opts.key) : "";
    const sub = opts.sub ? `<span class="sub">${opts.sub}</span>` : "";
    const place = opts.slot ? ` style="grid-column:${opts.slot}"` : "";
    return `<button class="${cls}"${place}${opts.fk ? ` data-fk="${opts.fk}"` : ""}${opts.off ? " disabled" : ""}${emit(opts.send)}>` +
           `<span class="label">${esc(opts.label)}${key}</span>${sub}</button>`;
  }
  // The first row: a word in small capitals, who or what, and a note.
  function whoseHtml(eyebrow, text, note, name) {
    // (the note is cut with an ellipsis where the bar is narrow: the full sentence is its tooltip;
    //  `name`: a player's name, written as it was typed, not in capitals)
    const who = name ? `<span class="who"> \u00b7 ${esc(name)}</span>` : "";
    return `<span class="eyebrow">${esc(eyebrow)}</span>${text ? `<b>${esc(text)}${who}</b>` : ""}${note ? `<span class="note" title="${esc(note)}">${esc(note)}</span>` : ""}`;
  }
  // (a row of five buttons or more is marked "many": where the bar is narrow its buttons go without keycaps)
  function barHtml(whose, buttons, slots) {
    const many = !slots && (buttons.match(/<button /g) || []).length >= 5 ? " many" : "";
    return `<div class="whose" data-fk="whose">${whose}</div><div class="${slots ? "slots" : "row" + many}">${buttons}</div>`;
  }

  function heroSeat(view) { return (view.table.seats || []).find((seat) => seat.is_hero) || null; }
  // Hero has nothing left to decide in the hand on screen: he folded, or was not dealt in.
  function heroOutOfHand(view) {
    const hero = heroSeat(view);
    return !!view.hand && (!hero || !hero.in_hand || hero.folded);
  }
  // Hero has no chips and no hand of his is running (view.hero_out; worked out here when the view does not say).
  function heroOutOfChips(view) {
    if (view.hero_out != null) return !!view.hero_out;
    const hero = heroSeat(view);
    return !!hero && hero.status === "busted" && (!view.hand || view.hand.needs === "next");
  }

  function actionsHtml(view, advice, ui) {
    const hand = view.hand;
    if (!hand) return betweenHandsBar(view);
    const selected = ui.selected != null ? (hand.line || []).find((event) => event.i === ui.selected) : null;
    if (selected) return eventBar(view, ui, selected);
    if (hand.needs === "cards") return cardsBar(view);
    if (hand.needs === "board") return boardBar(view);
    if (hand.needs === "result") return ui.split ? splitBar(view, ui) : resultBar(view, ui);
    if (hand.needs === "next") return nextBar(view);
    return actBar(view, advice, ui);
  }

  // Spin: is the game over (one player holds every chip)?
  function spinOver(view) { return view.mode === "spin" && !!(view.strip.game && view.strip.game.over); }
  // Spin games start with 300 chips each (x2 and x3) or 500 (x4 and up).
  function newGameButtons(primary) {
    return barButton({label: "New game", sub: "300 chips", key: primary ? "N" : "", primary: primary, wide: primary, fk: "game-300", send: {op: "new_game", start_stack: 300}}) +
           barButton({label: "New game", sub: "500 chips", fk: "game-500", send: {op: "new_game", start_stack: 500}});
  }
  const nextHandButton = (slot) => barButton({label: "Next hand", key: "N", primary: true, slot: slot, fk: "deal", send: {op: "deal"}});

  // Hero has no chips: the two things he can do, in place of Next hand.
  function outBar(view) {
    const again = view.mode === "tournament" ? "New tournament" : "New game";
    return barHtml(whoseHtml("You are out", "", "no chips on your seat"),
      barButton({label: "Re-enter", sub: "type your stack", key: "S", wide: true, fk: "reenter", send: {ui: only({seatMenu: 1, menuByKey: false})}}) +
      barButton({label: again, fk: "new-session", send: {ui: only({sheet: "new"})}}));
  }

  function betweenHandsBar(view) {
    if (spinOver(view)) return barHtml(whoseHtml("Game over", ""), newGameButtons(true));
    if (heroOutOfChips(view)) return outBar(view);
    if (view.mode === "spin") {
      return barHtml(whoseHtml("Between hands", ""),
        barButton({label: "New hand", key: "N", primary: true, wide: true, fk: "deal", send: {op: "deal"}}) +
        barButton({label: "Skip a hand", sub: "button moves on", fk: "skip", send: {op: "skip_hand"}}) + newGameButtons(false));
    }
    return barHtml(whoseHtml("Between hands", ""),
      barButton({label: "New hand", key: "N", primary: true, slot: "1 / 6", fk: "deal", send: {op: "deal"}}) +
      barButton({label: "Skip a hand", sub: "button moves on", slot: "6", fk: "skip", send: {op: "skip_hand"}}), true);
  }

  function cardsBar(view) {
    const want = view.hand.want_suits;
    return barHtml(whoseHtml("Your cards", "", want ? `the exact ${want.hand}` : ""),
      barButton({label: "Pick your cards", slot: "1 / 6", fk: "pick", send: {ui: only({picker: freshPicker("hero"), pickerOff: false})}}) +
      barButton({label: "Discard hand", slot: "6", fk: "discard", send: {op: "discard_hand"}}), true);
  }

  function boardBar(view) {
    const hand = view.hand;
    const count = (hand.board || []).length;
    const slot = count < 3 ? "flop" : count === 3 ? "turn" : "river";
    const out = heroOutOfHand(view);
    // Skipping a street gives everybody still to act a check. While the action is on hero that would
    // be his check too, so the button waits until he has acted (or is all-in, or out of the hand).
    return barHtml(whoseHtml("The " + slot, "", out ? "you are out of this hand" : ""),
      (out ? nextHandButton("1") : "") +
      barButton({label: `Pick the ${slot}`, slot: out ? "2 / 6" : "1 / 6", fk: "pick-" + slot,
                 send: {ui: only({picker: freshPicker(slot), pickerOff: false})}}) +
      // (named by its street: after a click the same words stand for the next street, and that is another button)
      barButton({label: "Skip the board", key: "Enter", slot: "6", fk: "skip-" + slot, off: !!hand.target_is_hero, send: {op: "close_round"}}), true);
  }

  // The players still in the pot who were not named a winner yet.
  function liveSeats(view, ui) {
    const ranked = [].concat.apply([], ui.awardTiers || []);
    return (view.table.seats || []).filter((seat) => !seat.empty && seat.in_hand && !seat.folded && ranked.indexOf(seat.seat) < 0);
  }

  // Who won. Each player still in gets a button; a side pot asks again for the next best hand.
  function resultBar(view, ui) {
    const tiers = ui.awardTiers || [];
    const live = liveSeats(view, ui);
    const hero = live.find((seat) => seat.is_hero);
    const others = live.filter((seat) => !seat.is_hero);
    const award = (seats) => ({op: "award", ranking: tiers.concat([seats]), ui: {seatMenu: null}});
    let buttons = heroOutOfHand(view) ? barButton({label: "Next hand", key: "N", primary: true, fk: "deal", send: {op: "deal"}}) : "";
    if (hero) buttons += barButton({label: "You won", key: "W", fk: "won-1", send: award([hero.seat])});
    if (hero && others.length === 1) {
      buttons += barButton({label: "You lost", key: "L", fk: "won-" + others[0].seat, send: award([others[0].seat])});
    } else {
      buttons += list(others.slice(0, 4), (seat) => barButton({label: `${seat.pos || seatName(seat)} won`, sub: esc(seatName(seat)), fk: "won-" + seat.seat, send: award([seat.seat])}));
    }
    // Two players: the split is between them. More: it asks who shares the pot (the others lose).
    if (live.length === 2) buttons += barButton({label: "Split", fk: "split", send: award(live.map((seat) => seat.seat))});
    else if (live.length > 2) buttons += barButton({label: "Split", sub: "tick who shares", fk: "split", send: {ui: {split: [], seatMenu: null}}});
    return barHtml(whoseHtml(tiers.length ? "Side pot" : "Showdown", tiers.length ? "Next best hand?" : "Who won?"), buttons);
  }

  // A split between some of the players of a showdown: a tick list, then one button.
  function splitBar(view, ui) {
    const tiers = ui.awardTiers || [];
    const live = liveSeats(view, ui);
    const ticked = (ui.split || []).filter((n) => live.some((seat) => seat.seat === n));
    const ticks = list(live, (seat) => {
      const on = ticked.indexOf(seat.seat) >= 0;
      const next = on ? ticked.filter((n) => n !== seat.seat) : ticked.concat([seat.seat]);
      return `<button class="btn tick" role="checkbox" aria-checked="${on}" data-fk="tick-${seat.seat}"${emit({ui: {split: next}})}>` +
             `<span class="label"><span class="box" aria-hidden="true"></span>${esc(seat.is_hero ? "You" : seat.pos || seatName(seat))}${keycap(String(seat.seat))}</span>` +
             `${seat.is_hero ? "" : `<span class="sub">${esc(seatName(seat))}</span>`}</button>`;
    });
    const enough = ticked.length >= 2;
    return barHtml(whoseHtml("Split pot", "Who shares it?", "tick two or more: the others lose"),
      ticks +
      barButton({label: "Split", key: "Enter", primary: enough, off: !enough, fk: "split-ok",
                 send: {op: "award", ranking: tiers.concat([ticked]), ui: {split: null, seatMenu: null}}}) +
      barButton({label: "Cancel", key: "Esc", fk: "split-cancel", send: {ui: {split: null}}}));
  }

  function nextBar(view) {
    if (spinOver(view)) return barHtml(whoseHtml("Game over", ""), newGameButtons(true));
    if (heroOutOfChips(view)) return outBar(view);
    // (Slot 6, where Rest fold was, stays empty: a second click there never deals a hand.)
    return barHtml(whoseHtml("Hand over", ""), nextHandButton("1 / 6"), true);
  }

  // What the Follow button will do, in words.
  function followText(view, follow) {
    if (!follow) return "";
    // All-In or Fold: answering an all-in is a call, and the bar's own button says Call with its price.
    const legal = (view.hand && view.hand.legal) || {};
    if (isAof(view) && legal.call != null && (follow.kind === "allin" || follow.kind === "call")) {
      return `call ${mainText(view, legal.call, view.hand.to_call_bb)}`;
    }
    const kind = follow.kind === "allin" ? "all-in" : follow.kind;
    if (follow.to == null || follow.kind === "allin") return kind;
    return `${kind} ${chipsOnlyText(view, follow.to)}`;
  }

  // "HJ · Seat 4" (the name, when the player has one, follows in its own letters).
  function seatWords(seat) {
    return [seat.pos, `Seat ${seat.seat}`].filter(Boolean).join(" \u00b7 ");
  }

  // The bar while a player has to act.
  function actBar(view, advice, ui) {
    const hand = view.hand;
    const seat = actingSeat(view, ui);
    const player = seatOf(view, seat);
    const isHero = !!(player && player.is_hero);
    const known = seat === hand.target;              // the legal moves in the view are for the server's next player
    const legal = hand.legal || {};
    // `plain`: the bar was not aimed at a seat, so this is the same as the plain key (see the controller: recording in turn).
    const plain = ui.target == null;
    const act = (kind) => ({op: "act", seat: seat, kind: kind, plain: plain, ui: AFTER_ACT});
    const ask = (kind) => ({ui: {amount: {kind: kind, seat: seat, plain: plain}, seatMenu: null, selected: null}});
    const can = (move) => !known || (legal[move] != null && legal[move] !== false);
    const who = isHero ? "hero" : "opp";             // a button that changes hands between hero and an opponent is another button
    const before = (hand.before_target || []).map((n) => seatOf(view, n)).filter(Boolean);

    // The first row: whose action the plain keys and the buttons record.
    let whose;
    if (isHero) {
      // Players in front of hero who have not acted take the passive default when he acts.
      const names = before.map((other) => other.pos || `Seat ${other.seat}`).join(", ");
      const note = before.length && known
        ? `before you: ${names} ${before.length === 1 ? (hand.to_call ? "folds" : "checks") : (hand.to_call ? "fold" : "check")} unless you press ${before.length === 1 ? "that seat's" : "their seat"} number first`
        : "";
      whose = whoseHtml("Your action", "", note);
    } else {
      whose = whoseHtml("Recording", player ? seatWords(player) : `Seat ${seat}`, !plain ? "this action only" : "", player && player.name);
    }

    // Slot 1: the coach's button.
    let first;
    if (heroOutOfHand(view)) {
      first = nextHandButton("1");
    } else {
      const follow = isHero && known && isCurrent(view, advice) ? advice.headline.follow : null;
      first = barButton({label: "Follow", key: "Space", primary: true, slot: "1", fk: "follow", off: !follow,
                         sub: esc(followText(view, follow)),
                         send: follow ? Object.assign({op: "act", seat: seat, via: "follow", ui: AFTER_ACT}, follow) : {}});
    }

    // Slots 2 to 5: the moves of the player the first row names.
    const fold = barButton({label: "Fold", key: "F", fk: "fold-" + who, off: !can("fold"), send: act("fold")});
    const callSub = known && legal.call != null ? esc(mainText(view, legal.call, hand.to_call_bb)) : "";
    const passive = known && legal.check
      ? barButton({label: "Check", key: "X", fk: "check-" + who, send: act("check")})
      : barButton({label: "Call", key: "C", fk: "call-" + who, sub: callSub, off: !can("call"), send: act("call")});
    const betting = known ? !!legal.bet : !hand.to_call;
    const raise = betting
      ? barButton({label: "Bet", key: "B", fk: "bet-" + who, off: !can("bet"), send: ask("bet")})
      : barButton({label: "Raise", key: "R", fk: "raise-" + who, off: !can("raise"), send: ask("raise")});
    const allinSub = known && legal.allin != null ? esc(chipsOnlyText(view, legal.allin, true)) : "";
    const allin = barButton({label: "All-in", key: "A", fk: "allin-" + who, sub: allinSub, off: !can("allin"), send: act("allin")});

    // Slot 6: the rest take the passive default. Hero's own action is always typed, so while the plain
    // keys are his the button waits. While players in front of him are recorded in turn, it ends that:
    // they fold, and the keys are hero's.
    const free = !hand.to_call;
    let rest;
    if (!hand.target_is_hero) {
      const next = seatOf(view, hand.target);
      rest = barButton({label: free ? "Rest check" : "Rest fold", key: "Enter", slot: "6", fk: "rest",
                        sub: esc(next ? `from ${next.pos || "seat " + next.seat}` : ""), send: {op: "close_round", ui: AFTER_ACT}});
    } else if (!isHero && plain) {
      rest = barButton({label: free ? "Rest check" : "Rest fold", key: "Enter", slot: "6", fk: "rest", sub: "then you", send: {ui: {turn: null}}});
    } else {
      rest = barButton({label: free ? "Rest check" : "Rest fold", key: "Enter", slot: "6", fk: "rest", off: true, sub: "after you", send: {}});
    }

    // All-In or Fold has two moves. A call of an all-in is an all-in.
    if (isAof(view)) {
      const shove = known && legal.call != null
        ? barButton({label: "Call", key: "C", fk: "call-" + who, sub: callSub, send: act("call")})
        : allin;
      return barHtml(whose, first + shove + fold + rest, true);
    }
    return barHtml(whose, first + fold + passive + raise + allin + rest, true);
  }

  // A selected event on the hand line: change its amount, change its cards, or delete it.
  // The cursor stays on the chip: Delete removes the action, E (or a second click) opens its amount.
  function eventBar(view, ui, event) {
    const done = barButton({label: "Done", key: "Esc", fk: "event-done", send: {ui: {selected: null, editing: null}}});
    if (isCardRun(event.text) || event.kind === "cards" || event.kind === "board") {
      // The first board event is the flop, then the turn, then the river (the event says so when the server names its street).
      const before = (view.hand.line || []).filter((other) => other.kind === "board" && other.i < event.i).length;
      const street = ["flop", "turn", "river"].indexOf(event.street) >= 0 ? event.street : ["flop", "turn", "river"][before] || "flop";
      const slot = event.kind === "board" ? street : "hero";
      return barHtml(whoseHtml("Selected", event.kind === "board" ? "The " + street : "Your cards"),
             barButton({label: "Change the cards", wide: true, fk: "event-cards", send: {ui: only({picker: freshPicker(slot, true)})}}) + done);
    }
    const hasAmount = eventHasAmount(event);
    let edit = "";
    if (hasAmount && ui.editing === event.i) {
      edit = `<form class="amount" data-from="event-amount"${emit({op: "edit_event", index: event.i, ui: {selected: null, editing: null}})}>
          <label class="field${isBad(ui, "event-amount") ? " bad" : ""}"><span class="eyebrow">Amount</span>
            ${amountInput(view, {name: "to", chips: event.to, fk: "event-amount", focus: true, bad: isBad(ui, "event-amount")})}</label>
          ${fieldErrorHtml(ui, ["event-amount"])}
          <button type="submit" class="btn compact">Save ${keycap("Enter")}</button></form>`;
    } else if (hasAmount) {
      edit = barButton({label: "Amount", key: "E", fk: "event-edit", send: {ui: {editing: event.i}}});
    }
    // A fold nobody typed (it follows from a later action) is where a forgotten caller is put in.
    const forgotten = event.auto && event.verb === "fold"
      ? barButton({label: "Called", fk: "event-called", send: {op: "edit_event", index: event.i, kind: "call", ui: {selected: null, editing: null}}}) +
        barButton({label: "Raised", fk: "event-raised", send: {op: "edit_event", index: event.i, kind: "raise", ui: {selected: null, editing: null}}})
      : "";
    // An action nobody typed cannot be deleted, only changed.
    return barHtml(whoseHtml("Selected", event.text, event.auto ? "nobody typed this: it follows from a later action" : ""),
      edit + forgotten +
      barButton({label: "Delete", key: "Del", fk: "event-delete", off: !!event.auto, send: {op: "remove_event", index: event.i, ui: {selected: null, editing: null}}}) + done);
  }
  function eventHasAmount(event) {
    return !!event && event.kind === "act" && event.to != null && ["bet", "raise", "call", "allin"].indexOf(event.verb) >= 0;
  }

  /* ---------- 8. Menus on the table: a seat, the cards, the table tools ---------- */

  function tableMenus(view, ui) {
    if (ui.picker && view.hand) return pickerHtml(view, ui.picker);
    if (ui.seatMenu != null) {
      const seat = seatOf(view, ui.seatMenu);
      if (seat) return seat.empty ? addPlayerHtml(view, ui, seat) : seatMenuHtml(view, ui, seat);
    }
    if (ui.menu === "table") return tableMenuHtml(view);
    if (ui.menu === "newtable") return newTableHtml(view, ui);
    return "";
  }

  // A table move: how many seats the new table has and where its dealer button is. Then every stack is typed.
  function newTableHtml(view, ui) {
    const limits = (view.settings && view.settings.size_limits) || [2, 9];
    const pick = ui.newTable || {};
    const size = Math.max(limits[0], Math.min(limits[1], pick.size || view.table.size));
    const button = Math.min(size, pick.button || view.table.button || 1);
    let sizes = "", seats = "";
    for (let n = limits[0]; n <= limits[1]; n++) {
      sizes += `<button type="button" class="tab" role="radio" aria-checked="${n === size}" data-fk="nt-size-${n}"${emit({ui: {newTable: {size: n, button: Math.min(button, n)}}})}>${n}</button>`;
    }
    for (let n = 1; n <= size; n++) {
      seats += `<button type="button" class="tab" role="radio" aria-checked="${n === button}" data-fk="nt-button-${n}"${emit({ui: {newTable: {size: size, button: n}}})}>${n === 1 ? "1 you" : n}</button>`;
    }
    return `<div class="pop" role="dialog" aria-label="New table">
      ${popHead("New table", "", {menu: null, newTable: null})}
      <p class="hint">You were moved: you stay seat 1, the tournament stays. The seats count clockwise from you.</p>
      <div class="choice"><span>Seats</span><div class="tabs" role="radiogroup" aria-label="Seats at the new table">${sizes}</div></div>
      <div class="choice"><span>Button</span><div class="tabs" role="radiogroup" aria-label="The seat with the dealer button">${seats}</div></div>
      <div class="row"><button type="button" class="menu-btn" data-fk="nt-start" data-autofocus` +
        `${emit({op: "new_table", size: size, button: button, ui: {menu: null, newTable: null}, after: {sheet: "stacks"}})}>Sit down: type the stacks ${keycap("Enter")}</button></div>
    </div>`;
  }

  // `name`: a player's name after the title, in its own letters (a heading is otherwise in capitals).
  function popHead(title, small, closePatch, name) {
    const who = name ? `<span class="who">${title ? " \u00b7 " : ""}${esc(name)}</span>` : "";
    return `<div class="pop-head"><h2>${esc(title)}${who}${small ? ` <small>${esc(small)}</small>` : ""}</h2>
      <button type="button" class="tool" aria-label="Close" title="Close"${emit({ui: closePatch})}>${icon("close")}</button></div>`;
  }

  // A labelled field that sends its text on Enter, and when it is left after a change
  // (`enterOnly`: on Enter only, so a click elsewhere never saves it; `bad`: the server refused its value;
  //  `over`: the label stands on a line over the field, for labels of two words in a narrow column).
  function fieldHtml(opts) {
    const input = `<input class="${opts.words ? "words" : ""}" value="${esc(opts.value == null ? "" : opts.value)}" data-name="${opts.name || "text"}" data-fk="${esc(opts.fk)}"
        ${opts.focus ? "data-autofocus" : ""} ${opts.enterOnly ? "data-enter-only" : ""} ${opts.bad ? 'aria-invalid="true"' : ""}
        ${opts.placeholder ? `placeholder="${esc(opts.placeholder)}"` : ""} autocomplete="off" spellcheck="false"${opts.unit || ""}${emit(opts.send)}>${opts.mark || ""}`;
    if (opts.over) {
      return `<label class="over"><span class="eyebrow">${esc(opts.label)}</span><span class="field${opts.bad ? " bad" : ""}">${input}</span></label>`;
    }
    return `<label class="field${opts.bad ? " bad" : ""}"><span class="eyebrow">${esc(opts.label)}</span>
      ${input}</label>`;
  }

  // A hand is being played (a settled one, waiting for the next deal, is not).
  function midHand(view) { return !!(view.hand && view.hand.needs !== "next"); }

  function seatMenuHtml(view, ui, seat) {
    const n = seat.seat;
    const closed = {seatMenu: null, target: null};
    // The fields of a seat are saved with Enter (or Save), never by a click elsewhere: a number typed
    // for something else must not become a stack. During a hand a click on a seat leaves the cursor
    // out of the stack field: the keys stay keys of the table.
    const inHand = midHand(view);
    const field = (opts) => fieldHtml(Object.assign({enterOnly: true, bad: isBad(ui, opts.fk)}, opts,
      "amount" in opts ? {unit: amountAttrs(view, opts.amount), mark: unitMark(view)} : {}));
    const stack = field({label: "Stack", value: plainAmount(view, seat.stack), fk: "seat-stack", focus: !inHand, amount: seat.stack,
                         send: {op: "set_stack", seat: n}});
    const refused = fieldErrorHtml(ui, ["seat-stack", "seat-name", "seat-note"]);
    const save = `<button class="menu-btn" data-save data-fk="seat-save" title="Save what you typed (Enter in a field does the same)" disabled>Save</button>`;
    const popFocus = inHand ? ' tabindex="-1" data-autofocus' : "";
    const away = seat.status === "away";
    const sit = `<button class="menu-btn"${emit({op: "set_status", seat: n, status: away ? "active" : "away"})}>${away ? "Sit back" : "Sit out"} ${keycap("O")}</button>`;
    const button = `<button class="menu-btn"${seat.is_button ? " disabled" : ""}${emit({op: "set_button", seat: n})}>Button ${keycap("D")}</button>`;
    // At a showdown the menu can also name this player the winner.
    const showdown = view.hand && view.hand.needs === "result" && seat.in_hand && !seat.folded;
    const won = showdown
      ? `<div class="row"><button class="menu-btn"${emit({op: "award", ranking: (ui.awardTiers || []).concat([[n]]), ui: closed})}>Won the pot ${keycap("W")}</button></div>`
      : "";
    if (seat.is_hero) {
      return `<div class="pop seat" role="dialog" aria-label="Your seat"${popFocus}>
        ${popHead(seat.pos || "", `seat ${n}`, closed, "You")}${won}
        ${stack}${refused}
        <div class="row">${sit}${button}${save}</div>
      </div>`;
    }
    const types = list(CHOICES.type, (type) => `<option value="${type}"${type === (seat.type || "unknown") ? " selected" : ""}>${type}</option>`);
    return `<div class="pop seat" role="dialog" aria-label="Seat ${n}"${popFocus}>
      ${popHead(seat.pos || "", `seat ${n}`, closed, seat.name)}${won}
      <div class="two">${stack}
        ${field({label: "Name", value: seat.name, words: true, name: "name", fk: "seat-name", send: {op: "rename", seat: n}})}
        <label class="field"><span class="eyebrow">Type</span><select data-name="type" data-fk="seat-type"${emit({op: "set_type", seat: n})}>${types}</select></label>
        ${field({label: "Note", value: seat.note, words: true, fk: "seat-note", send: {op: "note", seat: n}})}
      </div>${refused}
      <div class="row">${sit}${button}
        <button class="menu-btn"${emit({op: "bust", seat: n, ui: closed})}>Bust ${keycap("K")}</button>
        <button class="menu-btn"${emit({op: "clear_seat", seat: n, ui: closed})}>Clear ${keycap("Del")}</button>${save}</div>
    </div>`;
  }

  function addPlayerHtml(view, ui, seat) {
    const closed = {seatMenu: null, target: null};
    // The likeliest stack for a newcomer: the starting stack (All-In or Fold: the 8bb cap).
    const start = isAof(view) ? 8 : view.strip && view.strip.start_stack;
    return `<form class="pop" role="dialog" aria-label="Add a player to seat ${seat.seat}" data-from="add-stack"${emit({op: "seat_player", seat: seat.seat, ui: closed})}>
      ${popHead("Add a player", `seat ${seat.seat}`, closed)}
      <div class="two">
        <label class="field${isBad(ui, "add-stack") ? " bad" : ""}"><span class="eyebrow">Stack</span>${amountInput(view, {name: "stack", chips: start, fk: "add-stack", focus: true, bad: isBad(ui, "add-stack")})}</label>
        <label class="field"><span class="eyebrow">Name</span><input class="words" name="name" placeholder="optional" autocomplete="off" data-fk="add-name"></label>
      </div>${fieldErrorHtml(ui, ["add-stack"])}
      <div class="row"><button type="submit" class="menu-btn">Seat the player ${keycap("Enter")}</button>
        <button type="button" class="menu-btn" data-fk="button-here"${seat.is_button ? " disabled" : ""}${emit({op: "set_button", seat: seat.seat, ui: closed})}>Button here ${keycap("D")}</button></div>
    </form>`;
  }

  function tableMenuHtml(view) {
    const size = view.table.size;
    const closed = {menu: null};
    // Spin and All-In or Fold have a fixed number of seats; a tournament table has 2 to 9.
    const limits = (view.settings && view.settings.size_limits) || (view.mode === "tournament" ? [2, 9] : [size, size]);
    const sizeRow = limits[0] < limits[1]
      ? `<div class="row">
          <button class="menu-btn" aria-label="One seat fewer"${size <= limits[0] ? " disabled" : ""}${emit({op: "set_size", size: size - 1})}>${MINUS} Seat ${keycap("{")}</button>
          <span class="menu-count"><span class="num">${size}</span> seats</span>
          <button class="menu-btn" aria-label="One seat more"${size >= limits[1] ? " disabled" : ""}${emit({op: "set_size", size: size + 1})}>+ Seat ${keycap("}")}</button>
        </div>`
      : "";
    return `<div class="pop" role="dialog" aria-label="Table tools">
      ${popHead("Table", "", closed)}
      <div class="row">
        <button class="menu-btn" data-autofocus${emit({op: "button_step", step: -1})}>${keycap("[")} Button back</button>
        <button class="menu-btn"${emit({op: "button_step", step: 1})}>Button forward ${keycap("]")}</button>
      </div>
      ${sizeRow}
      <div class="row">
        <button class="menu-btn"${emit({ui: only({sheet: "stacks"})})}>Every stack</button>
        ${view.mode === "tournament" ? `<button class="menu-btn" data-fk="new-table"${emit({ui: {menu: "newtable", newTable: null}})}>New table</button>` : ""}
      </div>
      <div class="row">
        <button class="menu-btn"${emit({op: "skip_hand", ui: closed})}>Skip a hand</button>
        <button class="menu-btn"${view.hand ? "" : " disabled"}${emit({op: "discard_hand", ui: closed})}>Discard hand</button>
      </div>
    </div>`;
  }

  // The cards on the table that a pick must not repeat: a deck has one of each.
  function cardsInUse(view, picker) {
    const hand = view.hand;
    const board = hand.board || [];
    const keep = {hero: board, flop: board.slice(3), turn: board.slice(0, 3).concat(board.slice(4)), river: board.slice(0, 4)}[picker.slot] || [];
    const hero = picker.slot === "hero" ? [] : (hand.hero_cards || []);
    return keep.concat(hero, picker.cards || []);
  }

  // A picker that has just been opened for a slot: hero, flop, turn or river.
  // `replace`: the user opened it himself to change hero's cards.
  function freshPicker(slot, replace) { return {slot: slot, cards: [], rank: null, rank2: null, replace: !!(replace && slot === "hero")}; }
  function cardsNeeded(slot) { return slot === "flop" ? 3 : slot === "hero" ? 2 : 1; }

  // The exact holdings the table is asking for: hero's hand is on record as a class (AKs) and the flop
  // is out. Null when the user is changing his cards on purpose, or nothing of the kind is wanted.
  function wantSuits(view, picker) {
    const hand = view.hand;
    const want = hand && hand.want_suits;
    if (!want || !picker || picker.slot !== "hero" || picker.replace) return null;
    return Array.isArray(want.options) && want.options.length ? want : null;
  }

  // Hero's hand when it is known as a class only (AKs, AKo, 77): its suits can then be picked without the ranks.
  function classToSuit(view, picker) {
    const hand = view.hand;
    if (picker.slot !== "hero" || !hand || !hand.hero_class || (hand.hero_cards || []).length === 2) return "";
    return hand.hero_class;
  }

  /* One step of picking cards. A click on the picker and a key on the keyboard both come here.
       step: {rank: "A"} | {suit: "h"} | {mark: "s" | "o"} (suited, offsuit) | {back: true}
     Returns the event to send: a ui patch with the picker as it is after the step, or the set_cards
     intent when the slot is full. Returns null when the step makes no sense at this point. */
  function pickerStep(view, picker, step) {
    const slot = picker.slot;
    const cards = picker.cards || [];
    const used = cardsInUse(view, picker);
    const state = (next) => ({ui: {picker: Object.assign(freshPicker(slot, picker.replace), {cards: cards}, next)}});
    const done = (text) => Object.assign({op: "set_cards", slot: slot, text: text, ui: {picker: null, selected: null}},
                                         picker.replace ? {replace: true} : {});

    if (step.back) {
      if (picker.rank2) return state({rank: picker.rank});
      if (picker.rank) return state({});
      return cards.length ? state({cards: cards.slice(0, -1)}) : null;
    }
    if (step.rank) {
      const rank = step.rank;
      if (picker.rank2) return null;                              // two ranks are in: only suited or offsuit is left
      if (SUITS.split("").every((suit) => used.indexOf(rank + suit) >= 0)) return null;     // all four are on the table
      // Hero's hand as a class: a second rank straight after the first. A pair is complete, anything else waits for suited or offsuit.
      if (slot === "hero" && cards.length === 0 && picker.rank) {
        return rank === picker.rank ? done(rank + rank) : state({rank: picker.rank, rank2: rank});
      }
      return state({rank: rank});
    }
    if (step.mark) {
      if (!picker.rank || !picker.rank2) return null;
      // The higher rank is written first: K then A is still AKs.
      const pair = [picker.rank, picker.rank2].sort((a, b) => RANKS.indexOf(a) - RANKS.indexOf(b)).join("");
      return done(pair + step.mark);
    }
    if (step.suit) {
      if (picker.rank2) return null;
      let rank = picker.rank;
      const want = wantSuits(view, picker);
      if (!rank && want) {
        // The suit picks among the holdings asked for. A suited hand takes one suit for both cards; otherwise
        // the first suit is the first card's (the ace of AKo), the second the other card's.
        const known = (card) => want.options.some((option) => option.indexOf(card) >= 0);
        const chosen = cards.length === 1 && known(cards[0]) ? cards : [];      // (a stray card typed before is dropped)
        const open = want.options.filter((option) => chosen.every((card) => option.indexOf(card) >= 0));
        if (!chosen.length) {
          const both = open.find((option) => option[0][1] === step.suit && option[1][1] === step.suit);
          if (String(want.hand)[2] === "s") return both ? done(both.join("")) : null;
          const first = String(want.hand)[0] + step.suit;
          return open.some((option) => option.indexOf(first) >= 0) ? state({cards: [first]}) : null;
        }
        const match = open.find((option) => option.some((card) => card !== chosen[0] && card[1] === step.suit));
        return match ? done(match.join("")) : null;
      }
      const cls = classToSuit(view, picker);
      if (!rank && cls) {
        // The ranks are known from the class: a suit alone is enough. A suited hand takes one suit for both cards.
        if (cls[2] === "s" && cards.length === 0) {
          const both = [cls[0] + step.suit, cls[1] + step.suit];
          return both.some((card) => used.indexOf(card) >= 0) ? null : done(both.join(""));
        }
        rank = cls[cards.length];
      }
      if (!rank) return null;
      const card = rank + step.suit;
      if (used.indexOf(card) >= 0) return null;                   // a deck has one of each
      const picked = cards.concat([card]);
      return picked.length === cardsNeeded(slot) ? done(picked.join("")) : state({cards: picked});
    }
    return null;
  }

  // Rank, then suit, as on the keyboard. For hero's hand two ranks and "suited" or "offsuit" also do (A K S).
  function pickerHtml(view, picker) {
    const slot = picker.slot;
    const need = cardsNeeded(slot);
    const cards = picker.cards || [];
    const step = (what) => pickerStep(view, picker, what);
    if (wantSuits(view, picker)) return holdingsHtml(view, picker);

    const ranks = list(RANKS.split(""), (rank) => {
      const send = step({rank: rank});
      const on = rank === picker.rank || rank === picker.rank2;
      const next = !picker.rank && rank === "A" ? " data-autofocus" : "";
      return `<button type="button" class="pick${on ? " on" : ""}" data-fk="rank-${rank}" aria-label="${RANK_WORD[rank]}" aria-pressed="${on}"` +
             `${send ? "" : " disabled"}${next}${emit(send || {})}>${rankText(rank)}</button>`;
    });

    const suits = list(SUITS.split(""), (suit) => {
      const send = step({suit: suit});
      const next = picker.rank && !picker.rank2 ? " data-autofocus" : "";
      return `<button type="button" class="pick" data-fk="suit-${suit}" aria-label="${SUIT_WORD[suit]}"${send ? "" : " disabled"}${next}${emit(send || {})}>${suitSvg(suit)}</button>`;
    });

    let classButtons = "";
    if (slot === "hero") {
      classButtons = ["s", "o"].map((mark) => {
        const send = step({mark: mark});
        return `<button type="button" class="pick word" data-fk="class-${mark}"${send ? " data-autofocus" : " disabled"}${emit(send || {})}>${mark === "s" ? "Suited" : "Offsuit"}</button>`;
      }).join("");
    }

    // The slots at the top show how far the pick is.
    let shown = list(cards, (code) => cardHtml(code));
    let filled = cards.length;
    if (picker.rank) { shown += rankCardHtml(picker.rank, "", false); filled += 1; }
    if (picker.rank2) { shown += rankCardHtml(picker.rank2, "", false); filled += 1; }
    for (let i = filled; i < need; i++) shown += slotHtml(i === filled, false);

    // A hand typed as a class needs its suits once the flop is out: say which keys do it.
    const cls = classToSuit(view, picker);
    let hint = "";
    if (cls && !picker.rank && view.hand.needs === "cards") {
      const ask = cls[2] === "s" ? `the suit of your ${cls}` : `the suit of the ${rankText(cls[0])}, then of the ${cards.length ? "other " : ""}${rankText(cls[1])}`;
      hint = `<p class="hint">After the flop the coach needs your exact cards: pick ${esc(ask)} (or both cards again).</p>`;
    }

    const title = {hero: "Your cards", flop: "Flop", turn: "Turn", river: "River"}[slot];
    const back = step({back: true});
    return `<div class="pop picker" role="dialog" aria-label="${title}: pick a rank, then a suit">
      <div class="pop-head"><h2>${title}</h2><div class="slots" aria-hidden="true">${shown}</div>
        <div class="pop-tools"><button class="tool" aria-label="Back one step" title="Back one step"${back ? "" : " disabled"}${emit(back || {})}>${icon("undo")}</button>
        <button class="tool" aria-label="Close" title="Close"${emit({ui: {picker: null, pickerOff: true}})}>${icon("close")}</button></div></div>
      ${hint}
      <div class="ranks">${ranks}</div>
      <div class="suits${slot === "hero" ? " with-class" : ""}">${suits}${classButtons}</div>
    </div>`;
  }

  // Hero's hand is on record as a class and the exact cards are wanted now: only the holdings of that
  // class that are still possible are offered, one button each. A suit key picks among them.
  function holdingsHtml(view, picker) {
    const want = wantSuits(view, picker);
    const cards = picker.cards || [];
    const chosen = cards.length === 1 && want.options.some((option) => option.indexOf(cards[0]) >= 0) ? cards[0] : null;
    const send = (option) => ({op: "set_cards", slot: "hero", text: option.join(""), ui: {picker: null, selected: null}});
    const buttons = list(want.options, (option, at) => {
      const off = chosen && option.indexOf(chosen) < 0;
      return `<button type="button" class="pick holding" data-fk="hold-${option.join("")}" aria-label="${esc(option.map(cardWords).join(", "))}"` +
             `${off ? " disabled" : ""}${at === 0 ? " data-autofocus" : ""}${emit(send(option))}>${cardHtml(option[0])}${cardHtml(option[1])}</button>`;
    });
    let shown = list(cards, (code) => cardHtml(code));
    if (picker.rank) shown += rankCardHtml(picker.rank, "", false);
    for (let i = cards.length + (picker.rank ? 1 : 0); i < 2; i++) shown += slotHtml(false, false);
    const hand = String(want.hand);
    const keys = hand[2] === "s" ? "Key: the suit (S H D C)."
      : hand[0] === hand[1] ? "Keys: the two suits."
      : `Keys: the suit of the ${rankText(hand[0])}, then the suit of the ${rankText(hand[1])}.`;
    const back = pickerStep(view, picker, {back: true});
    return `<div class="pop picker" role="dialog" aria-label="Your cards: which ${esc(hand)}">
      <div class="pop-head"><h2>Your cards</h2><div class="slots" aria-hidden="true">${shown}</div>
        <div class="pop-tools"><button class="tool" aria-label="Back one step" title="Back one step"${back ? "" : " disabled"}${emit(back || {})}>${icon("undo")}</button>
        <button class="tool" aria-label="Close" title="Close"${emit({ui: {picker: null, pickerOff: true}})}>${icon("close")}</button></div></div>
      <p class="hint">After the flop the coach needs your exact cards. Which ${esc(hand)} is it? ${esc(keys)}</p>
      <div class="holdings n${want.options.length > 6 ? 12 : want.options.length > 4 ? 6 : 4}">${buttons}</div>
      <div class="row"><button type="button" class="menu-btn" data-fk="other-cards"${emit({ui: {picker: freshPicker("hero", true)}})}>It was another hand: type the cards again</button></div>
    </div>`;
  }

  /* ---------- 9. Sheets ---------- */

  // A toast shows where the user is working: inside the open sheet, else beside the advice.
  let sheetToast = "";

  function sheetHtml(title, body, side) {
    const focusClose = body.indexOf("data-autofocus") < 0 ? " data-autofocus" : "";
    return `<button class="scrim" tabindex="-1" aria-label="Close"${emit({ui: {sheet: null}})}></button>
      <div class="sheet${side ? " side" : ""}" role="dialog" aria-modal="true" aria-label="${esc(title)}">
        <div class="sheet-head"><h2>${esc(title)}</h2>
          <button class="tool" aria-label="Close" title="Close"${focusClose}${emit({ui: {sheet: null}})}>${icon("close")}</button></div>
        <div class="sheet-body">${body}</div>
        ${sheetToast ? `<div class="sheet-toast" role="status">${sheetToast}</div>` : ""}
      </div>`;
  }

  function overlayHtml(view, advice, ui, mode) {
    if (!view) {
      if (ui.sheet === "keys") return sheetHtml("Keys", keysBody());
      if (ui.sheet === "settings") return sheetHtml("Settings", firstRunMenu(), true);
      // (from the screen that says the table cannot be shown: a way to start again)
      if (ui.sheet === "new") return sheetHtml(mode === "tournament" ? "New tournament" : "New game", setupForm(mode, null));
      return "";
    }
    if (ui.sheet === "settings") return sheetHtml("Settings", settingsBody(view, ui), true);
    if (ui.sheet === "why") return sheetHtml("Why and range", whyBody(view, advice));
    if (ui.sheet === "keys") return sheetHtml("Keys", keysBody());
    if (ui.sheet === "history") return sheetHtml("Hand history", historyBody(view, ui));
    if (ui.sheet === "new") {
      // A session is running: say what Start does to it, and how to get it back.
      const what = view.mode === "tournament" ? "tournament" : "game";
      const hands = (view.history || []).length;
      const note = `<p class="notice" data-fk="replace-note">Start replaces the ${what} that is running` +
                   `${hands ? ` (${hands} hand${hands === 1 ? "" : "s"} recorded)` : ""}. Undo brings it back.</p>`;
      return sheetHtml(view.mode === "tournament" ? "New tournament" : "New game", note + setupForm(view.mode, view.setup));
    }
    if (ui.sheet === "stacks") return sheetHtml("Every stack", stacksBody(view));
    return "";
  }

  const NOTICE = "For study and play money. Real-money sites ban real-time help.";

  function firstRunMenu() {
    return `<p class="notice">${NOTICE}</p>
      <div class="buttons"><button class="btn compact"${emit({ui: only({sheet: "keys"})})}>Keys ${keycap("?")}</button></div>`;
  }

  function whyBody(view, advice) {
    const live = isCurrent(view, advice);
    // (the spot in full: the narrow slab shows one line of it)
    const spot = live && advice.spot ? `<p class="spot-full" data-fk="why-spot">${prose(advice.spot)}</p>` : "";
    const body = whyHtml(advice, live) + (live ? chartHtml(advice.chart) : "") + contextHtml(advice);
    return body ? spot + body : `<p class="empty-note">Nothing to explain yet.</p>`;
  }

  function section(title, body) { return `<div class="section"><h3>${esc(title)}</h3>${body}</div>`; }
  function choiceRow(label, choices, current, send) {
    return `<div class="choice"><span>${esc(label)}</span>${choiceHtml(label, choices, current, send)}</div>`;
  }
  // A choice between things that need a line of explanation each ("Turbo (5 to 6 minute levels)"): the
  // label stands over the track, and each choice shows its name with the words in brackets under it.
  function choiceStack(label, choices, current, send) {
    const buttons = list(choices, (choice) => {
      const parts = /^(.*?)\s*\((.*)\)\s*$/.exec(choice.label);
      const words = parts ? `<b>${esc(parts[1])}</b><small>${esc(parts[2])}</small>` : `<b>${esc(choice.label)}</b>`;
      return `<button class="tab" role="radio" aria-checked="${choice.value === current}" aria-label="${esc(choice.label)}"${emit(send(choice.value))}>${words}</button>`;
    });
    return `<div class="choice stack"><span>${esc(label)}</span><div class="tabs" role="radiogroup" aria-label="${esc(label)}">${buttons}</div></div>`;
  }
  function checkHtml(label, on, send) {
    return `<label class="check"><input type="checkbox"${on ? " checked" : ""} data-name="value"${emit(send)}><span>${esc(label)}</span></label>`;
  }

  /* What the coach counts with, in a sentence: chips only, or prize money (ICM) and from which prizes.
     strip.icm is off | estimated | on | exact; it is exact only when a prize is typed for every paid
     place, so with fewer the sentence says how many of the places have one (strip.prizes_typed). */
  function prizeWords(strip) {
    const level = strip.icm;
    if (!level || level === "off") return "The coach counts chips only. With players left and places paid it counts prize money (ICM).";
    const typed = strip.prizes_typed != null ? strip.prizes_typed : Array.isArray(strip.payouts) ? strip.payouts.length : 0;
    const paid = strip.paid;
    const rough = level === "estimated" ? " The size of the field is estimated from this table: add the entrants and the start stack." : "";
    if (typed && paid && typed >= paid) return `The coach counts prize money (ICM) from the prizes you typed: one for each of the ${fmtChips(paid)} paid places.` + rough;
    if (typed) {
      const places = paid ? `${fmtChips(typed)} of the ${fmtChips(paid)} paid places` : `${fmtChips(typed)} place${typed === 1 ? "" : "s"}`;
      return `The coach counts prize money (ICM). A prize is typed for ${places}; the places below take the last one typed.` + rough;
    }
    return "The coach counts prize money (ICM) from typical payouts. Type the prizes for the real ones: 1:1000 2:600 4-6:200." + rough;
  }

  // Prizes from first place down, written the way they are typed: [1000, 600, 200, 200] -> "1:1000 2:600 3-4:200".
  function payoutsText(strip) {
    if (typeof strip.payouts_text === "string") return strip.payouts_text;
    if (typeof strip.payouts === "string") return strip.payouts;
    const prizes = Array.isArray(strip.payouts) ? strip.payouts : [];
    const words = [];
    for (let i = 0; i < prizes.length; i++) {
      let last = i;
      while (last + 1 < prizes.length && prizes[last + 1] === prizes[i]) last++;
      words.push((last > i ? `${i + 1}-${last + 1}` : `${i + 1}`) + ":" + prizes[i]);
      i = last;
    }
    return words.join(" ");
  }

  function settingsBody(view, ui) {
    const strip = view.strip || {};
    const config = (key) => (value) => ({op: "set_config", key: key, value: value});
    const tourney = (label, field, value, opts) => fieldHtml(Object.assign(
      {label: label, value: value, over: true, fk: "set-" + field, bad: isBad(ui, "set-" + field), send: {op: "set_tournament", field: field}}, opts || {}));
    let html = `<p class="notice">${NOTICE}</p>`;

    if (view.mode === "tournament") {
      html += section("Tournament", `<div class="cols">
          ${fieldHtml({label: "Players left", value: strip.remaining, over: true, fk: "set-remaining", bad: isBad(ui, "set-remaining"), send: {op: "remaining"}})}
          ${tourney("Places paid", "paid", strip.paid)}
          ${tourney("Entrants", "entrants", strip.entrants)}
          ${tourney("Start stack", "start_stack", strip.start_stack)}
          ${tourney("Average stack", "avg_stack", strip.avg_stack)}
          ${tourney("Buy-in", "buyin", strip.buyin)}
        </div>
        ${tourney("Payouts", "payouts", payoutsText(strip), {words: true, placeholder: "auto, or 1:1000 2:600 4-6:200"})}
        <p class="hint" data-fk="prize-words">${esc(prizeWords(strip))}</p>
        ${checkHtml("Re-entry is still open", strip.reentry_open, {op: "set_tournament", field: "reentry_open"})}
        ${checkHtml("Bounty tournament", strip.bounty, {op: "set_tournament", field: "bounty"})}`);
      html += section("Coach",
        choiceRow("Style", CHOICES.style, strip.style, config("style")) +
        choiceRow("Moves", CHOICES.plan, strip.plan, config("plan")) +
        choiceRow("Opponents", CHOICES.opponents.tournament, strip.opponents, config("opponents")));
    } else {
      html += section("Coach", choiceRow("Opponents", CHOICES.opponents[view.mode], strip.opponents, config("opponents")));
    }

    if (view.mode !== "aof") {
      const level = strip.level || {};
      const settings = view.settings || {};
      // The ladders the server knows, as an either-or; the levels of the one in use, ready to be edited.
      const ladders = (settings.ladders || []).map((ladder) => ({value: ladder.name, label: ladder.label || ladder.name}));
      const presets = ladders.length > 1 ? choiceStack("Blind levels", ladders, settings.ladder, (name) => ({op: "set_ladder", name: name})) : "";
      const levels = settings.ladder_text != null ? settings.ladder_text
        : (settings.levels || []).map((level) => level.filter((part, at) => at < 2 || part).join("/")).join("\n");
      html += section("Blinds",
        choiceRow("Ante", CHOICES.ante_kind, level.ante_kind || "none", (kind) => ({op: "set_ante_kind", kind: kind})) +
        presets +
        `<form class="stacked"${emit({op: "set_ladder"})}><textarea class="in" name="text" aria-label="Blind levels, one level per line: small blind / big blind / ante"
            placeholder="Levels of your own, one per line:&#10;100/200/25&#10;150/300/40">${esc(levels)}</textarea>
          <div class="buttons"><button type="submit" class="btn compact">Use these levels</button></div></form>`);
    }

    if (view.mode !== "aof") {
      const rule = buttonRule(view);
      html += section("Table",
        choiceRow("Dealer button", CHOICES.button_rule, rule, config("button_rule")) +
        `<p class="hint">Dead button: after a player busts the big blind still moves on by one player, so the button can stand on an empty seat for a hand. Most sites deal this way.</p>
         <p class="hint">Forward-moving button: the button always goes to the next player.</p>
         <p class="hint">[ and ] move the button by hand, also onto an empty seat.</p>`);
    }
    html += section("Screen",
      (view.mode === "aof" ? "" : choiceRow("Numbers in", CHOICES.unit, view.unit, config("unit"))) +
      choiceRow("Deck", CHOICES.deck, view.deck || "one-ink", config("deck")) +
      `<p class="hint">Two colours: black suits on white cards, with hearts and diamonds drawn as outlines. Four colours: red hearts, blue diamonds, green clubs.</p>`);
    html += section("Session", `<div class="buttons">
        <button class="btn compact"${emit({ui: only({sheet: "new"})})}>${view.mode === "tournament" ? "New tournament" : "New game"}</button>
        <button class="btn compact"${emit({ui: only({sheet: "history"})})}>Hand history ${keycap("Y")}</button>
        <button class="btn compact"${emit({ui: only({sheet: "keys"})})}>Keys ${keycap("?")}</button>
      </div>`);
    return html;
  }

  // One key of the map as keycaps: "Ctrl+Backspace" is two caps, "a k s" three keys typed one after the other.
  function comboHtml(name) {
    const caps = name.length > 1 && name.indexOf("+") > 0 ? name.split("+") : name.split(" ");
    return `<span class="combo">${list(caps, (cap) => keycap(KEY_WORDS[cap] || cap))}</span>`;
  }
  function keyRows(rows) {
    return `<dl class="keys">` + list(rows, (row) => {
      // A row of the server's key map is {keys, do, text}; the fixed rows above are [keys, text].
      const keys = Array.isArray(row) ? row[0] : row.keys;
      const text = Array.isArray(row) ? row[1] : row.text;
      return `<dt>${list(keys, comboHtml)}</dt><dd>${esc(text)}</dd>`;
    }) + `</dl>`;
  }
  // The key map that came with the last view; it is kept so the list also shows on the first-run screen.
  let keyMap = null;
  function keysBody() {
    const map = keyMap || {};
    return section("At the table", keyRows(map.table || [])) +
           section("Cards (while the card picker is open)", keyRows(CARD_KEYS)) +
           section("After a seat number", keyRows(SEAT_DIGIT_KEYS.concat(map.seat || []))) +
           (map.type ? section("Player types (seat number, T, then)", keyRows(map.type)) : "");
  }

  // What hero did, as a word: the server writes "allin".
  function didWord(did) { return did === "allin" ? "all-in" : did || "none"; }
  // The same in a sentence about a finished hand: "you raised".
  const DID_PAST = {fold: "folded", check: "checked", call: "called", bet: "bet", raise: "raised", allin: "moved all-in"};
  function didPast(did) { return DID_PAST[did] || (did ? String(did) : "did nothing"); }

  // A row is a button: it opens that hand's text, with its own Copy.
  function historyBody(view, ui) {
    const hands = view.history || [];
    if (!hands.length) return `<p class="empty-note">No hands yet. Each hand lands here with what the coach said and what you did.</p>`;
    const rows = list(hands, (hand) => {
      const cards = isCardRun(hand.cards) ? cardsInline(hand.cards) : esc(hand.cards || "");
      const look = hand.net > 0 ? " win" : hand.net < 0 ? " loss" : "";
      const net = hand.net ? plus(hand.net, chipsOnlyText(view, hand.net)) : "0";
      const open = ui.handOpen === hand.no;
      const row = `<button class="hrow" aria-expanded="${open}" data-fk="hand-${esc(hand.no)}"${emit({ui: {handOpen: open ? null : hand.no}})}>
        <span class="num">${esc(hand.no)}</span><b>${cards}</b><span>${esc(hand.pos || "")}</span>
        <span>${hand.skipped ? "not recorded" : `${hand.advice ? `coach <b>${esc(String(hand.advice).toLowerCase())}</b>` : "no advice"}, you <b>${esc(didPast(hand.did))}</b>`}${hand.deviated ? ' <span class="pill near">deviated</span>' : ""}</span>
        <span class="num${look}">${net}</span></button>`;
      if (!open) return row;
      return row + `<div class="htext"><pre>${esc(hand.text || "Nothing was recorded for this hand.")}</pre>
        <div class="buttons"><button class="btn compact" data-fk="copy-hand"${emit({cmd: "copy", text: hand.text || ""})}>Copy this hand</button></div></div>`;
    });
    const text = hands.map((hand) => hand.text || "").join("\n");
    return `<div class="buttons"><button class="btn compact" data-fk="copy-all"${emit({cmd: "copy", text: text})}>Copy as text</button></div>
      <div class="history">${rows}</div>`;
  }

  // Every stack at once, clockwise from hero. Blank keeps the stack.
  function stacksBody(view) {
    const seats = (view.table.seats || []).filter((seat) => !seat.empty);
    // Who it is stands on a line of its own over the field (seat number, position, the name as it was typed),
    // so a long name never takes the room of the number.
    const fields = list(seats, (seat, at) =>
      `<label class="sweep"><span class="who"><span class="key">${seat.seat}</span>${seat.pos ? `<b>${esc(seat.pos)}</b>` : ""}` +
        `<span class="name" title="${esc(seatName(seat))}">${esc(seatName(seat))}</span></span>
        <span class="field">${amountInput(view, {name: String(seat.seat), chips: seat.stack, fk: "sweep-" + seat.seat, focus: at === 0,
                                                   label: `Stack of seat ${seat.seat}, ${seatTitle(seat)}`})}</span></label>`);
    const how = typesBb(view) ? "Type what you see, in big blinds: 25, 33.5. Chips need their sign: 12.5k, 12,500 chips is 12.5k."
      : "Type what you see: 12.5k, 25bb, +3k.";
    return `<form class="stacked"${emit({op: "set_stacks", ui: {sheet: null}})} data-into="stacks" data-changed-only data-hold>
      <p class="hint">${how} A stack you leave as it is stays as it is (a ~ stays unsure); a minus sign empties the seat. Enter goes to the next seat and saves after the last.</p>
      <div class="cols sweeps">${fields}</div>
      <div class="buttons"><button type="submit" class="btn compact">Save ${keycap("Enter")}</button></div>
    </form>`;
  }

  /* ---------- 10. First run ---------- */

  // The likeliest values. The server may send its own under view.setup.
  const SETUP_DEFAULTS = {
    // (the level as it will be played: the first level of the blind levels has an ante of 12)
    tournament: {size: "8", start_stack: "10000", level: "50/100/12", hero_stack: "", entrants: "", remaining: "", paid: "", buyin: ""},
    spin: {start_stack: "300", level: "10/20"},
    aof: {},
  };

  function setupField(label, name, value, opts) {
    const o = opts || {};
    return `<label class="field"><span class="eyebrow">${esc(label)}</span>
      <input class="${o.words ? "words" : ""}" name="${name}" value="${esc(value == null ? "" : value)}" ${o.placeholder ? `placeholder="${esc(o.placeholder)}"` : ""}
        autocomplete="off" data-fk="setup-${name}"${o.focus ? " data-autofocus" : ""}></label>`;
  }
  function setupSelect(label, name, value, options) {
    return `<label class="field"><span class="eyebrow">${esc(label)}</span><select name="${name}" data-fk="setup-${name}">` +
      list(options, (option) => `<option value="${esc(option.value)}"${String(option.value) === String(value) ? " selected" : ""}>${esc(option.label)}</option>`) +
      `</select></label>`;
  }

  function setupForm(mode, sent) {
    const d = Object.assign({}, SETUP_DEFAULTS[mode], sent || {});
    let fields;
    if (mode === "spin") {
      fields = `<div class="cols">
          ${setupSelect("Stacks", "start_stack", d.start_stack, [{value: "300", label: "300 chips (x2, x3)"}, {value: "500", label: "500 chips (x4 and up)"}])}
          ${setupField("Blinds", "level", d.level)}
        </div>
        <p class="hint">Three players, winner takes all. You are seat 1.</p>`;
    } else if (mode === "aof") {
      fields = `<p class="hint">Four seats, 8 big blinds each, blinds 0.5 and 1. Everything is counted in big blinds.
        Clear a seat at the table when fewer than four play.</p>`;
    } else {
      const sizes = [2, 3, 4, 5, 6, 7, 8, 9].map((n) => ({value: String(n), label: `${n} seats`}));
      fields = `<div class="cols">
          ${setupSelect("Table", "size", d.size, sizes)}
          ${setupField("Blinds / ante", "level", d.level, {focus: true})}
          ${setupField("Start stack", "start_stack", d.start_stack)}
          ${setupField("Your stack", "hero_stack", d.hero_stack, {placeholder: "same"})}
          ${setupField("Entrants", "entrants", d.entrants, {placeholder: "optional"})}
          ${setupField("Players left", "remaining", d.remaining, {placeholder: "optional"})}
          ${setupField("Places paid", "paid", d.paid, {placeholder: "optional"})}
          ${setupField("Buy-in", "buyin", d.buyin, {placeholder: "optional"})}
        </div>
        <p class="hint">Blinds / ante: 50/100/12 is small blind, big blind, ante; 50/100/0 plays without an ante.
          Every field can be changed later. With players left and places paid the coach counts prize money, not only chips.</p>`;
    }
    return `<form class="stacked" data-hold${emit({op: "new_session", mode: mode, ui: {sheet: null}})}>${fields}
      <button type="submit" class="btn primary start">Start ${keycap("Enter")}</button></form>`;
  }

  function firstRunHtml(mode, sent) {
    const title = {tournament: "New tournament", spin: "New Spin & Gold", aof: "All-In or Fold"}[mode];
    return `<div class="setup">
      <h1>${title}</h1>
      <p class="lead">You type what you see at the table; the coach answers. Nothing reads the screen and nothing clicks for you.</p>
      ${setupForm(mode, sent)}
      <p class="notice">${NOTICE}</p>
    </div>`;
  }

  // The program could not show the table (its answer was an error), or does not answer at all.
  function viewErrorHtml(error, mode) {
    const again = mode === "tournament" ? "Start a new tournament" : "Start a new game";
    const ways = error.down ? "" :
      `<button class="btn compact" data-fk="trouble-undo"${emit({op: "undo"})}>Undo the last change</button>
       <button class="btn compact" data-fk="trouble-new"${emit({ui: {sheet: "new"}})}>${again}</button>`;
    return `<div class="setup trouble" role="alert">
      <h1>${error.down ? "No answer" : "The table cannot be shown"}</h1>
      <p class="lead">${esc(error.message || "")}</p>
      ${error.fix ? `<p class="hint">${esc(error.fix)}</p>` : ""}
      <div class="buttons">${ways}
        <button class="btn compact" data-fk="trouble-again"${emit({cmd: "reload"})}>Try again</button></div>
    </div>`;
  }

  /* ---------- 11. Toast ---------- */

  function toastHtml(view, ui) {
    const toast = ui.toast !== undefined ? ui.toast : view && view.toast;
    if (!toast) return "";
    const text = typeof toast === "string" ? toast : toast.text || toast.message;
    const fix = toast.fix ? `<small>${esc(toast.fix)}</small>` : "";
    const undo = toast.undo ? `<button class="link" data-fk="toast-undo"${emit({op: "undo", ui: {toast: null}})}>Undo</button>` : "";
    // After an undo the button beside "Undone" makes the step again (it does not undo one more).
    const redo = toast.redo ? `<button class="link" data-fk="toast-redo"${emit({op: "redo", ui: {toast: null}})}>Redo</button>` : "";
    // A refusal may offer the way round it as a button ("Clear seat 8 and remove it").
    const action = toast.action ? `<button class="link" data-fk="toast-action"${emit(Object.assign({ui: {toast: null}}, toast.action.send))}>${esc(toast.action.label)}</button>` : "";
    return `<div class="toast${toast.error ? " refusal" : ""}"><span class="text">${esc(text)}${fix}</span>${action}${undo}${redo}
      <button class="tool" aria-label="Dismiss" title="Dismiss"${emit({ui: {toast: null}})}>${icon("close")}</button></div>`;
  }

  /* ---------- 12. Drawing into the page, focus, events ---------- */

  const drawn = {};            // the HTML last put into each part, to skip parts that did not change
  let openBefore = "";         // which menu or sheet was open at the last draw
  let opener = null;           // the control that opened it: focus goes back there when it closes
  let lastUsed = null;         // the control that sent the last event

  function part(name) { return document.getElementById("region-" + name); }

  function put(name, html) {
    if (drawn[name] === html) return false;
    drawn[name] = html;
    part(name).innerHTML = html;
    return true;
  }

  // A name for a control that survives a redraw: its data-fk, else what it sends.
  function focusKey(element) {
    if (!element || !element.dataset) return null;
    return element.dataset.fk || element.dataset.emit || null;
  }
  function findByKey(key) {
    if (!key) return null;
    const all = document.querySelectorAll("[data-fk],[data-emit]");
    for (let i = 0; i < all.length; i++) if (focusKey(all[i]) === key && !all[i].disabled) return all[i];
    return null;
  }

  // The topmost open thing, as a word: used to move the focus in when it opens and back when it closes.
  function openThing(ui) {
    if (ui.sheet) return "sheet:" + ui.sheet;
    if (ui.picker) return ["picker", (ui.picker.cards || []).length, ui.picker.rank, ui.picker.rank2].join(":");
    if (ui.seatMenu != null) return "seat:" + ui.seatMenu;
    if (ui.menu) return "menu:" + ui.menu;
    if (ui.amount) return "amount";
    if (ui.selected != null) return ui.editing != null ? "event:amount" : "event";
    if (ui.edit) return "edit:" + ui.edit;
    return "";
  }

  function closeTopPatch(ui) {
    ui = ui || {};
    if (ui.sheet) return {sheet: null, fieldError: null};
    if (ui.picker) return {picker: null, pickerOff: true};
    if (ui.seatMenu != null) return {seatMenu: null, target: null, fieldError: null};
    if (ui.menu) return {menu: null, newTable: null};
    if (ui.amount) return {amount: null, fieldError: null};
    if (ui.split) return {split: null};
    if (ui.selected != null) return {selected: null, editing: null, fieldError: null};
    if (ui.edit) return {edit: null, fieldError: null};
    if (ui.target != null) return {target: null};
    if (ui.turn) return {turn: null};                         // the plain keys are hero's again
    return null;
  }

  // True while the page is being drawn: a field that is replaced then loses the focus, and the
  // browser tells it "changed". That is no click elsewhere by the user, so nothing is sent for it.
  let drawing = false;

  function render(view, advice, ui) {
    drawing = true;
    try { renderParts(view, advice, ui); } finally { drawing = false; }
  }

  function renderParts(view, advice, ui) {
    ui = ui || {};
    const setup = view && view.setup;                         // the server's own defaults for the first form, if any
    if (view && view.settings && view.settings.keys) keyMap = view.settings.keys;
    const mode = (view && view.mode) || ui.setupMode || "tournament";
    const can = (view && view.can) || {};
    // A view that is neither a table nor a first run cannot be shown: the page says so (never the form).
    if (view && !view.table && !view.first_run && !ui.viewError) {
      ui = Object.assign({}, ui, {viewError: {message: "The program could not show the table.", fix: "Undo takes back the last change."}});
    }
    if (view && (!view.table || view.first_run)) view = null; // nothing recorded yet: the first-run form
    const app = document.getElementById("app");

    // Remember where the keyboard is, and what was being typed there.
    const active = document.activeElement;
    const activeKey = focusKey(active);
    // (A value the server refused was sent, and is kept all the same: the field stays open with it.)
    const typing = active && active.dataset && active.dataset.dirty && (!active.dataset.sent || isBad(ui, activeKey))
      ? {value: active.value, start: active.selectionStart, end: active.selectionEnd} : null;
    const halfTyped = typedFields();

    app.className = "app" + (view ? "" : " first") + (view && view.deck === "four-colour" ? " deck-four" : "");
    put("header", headerHtml(view, ui, mode, can));
    if (view) {
      const adviceParts = adviceHtml(view, advice, ui);
      part("advice").dataset.panel = adviceParts.panel;
      put("advice", adviceParts.html);
      part("table").classList.toggle("aof", isAof(view));
      part("table").dataset.size = view.table.size;
      put("table", tableHtml(view, ui));
      const events = part("line").querySelector(".events");
      const scrolled = events ? events.scrollLeft : 0;
      if (put("line", lineHtml(view, ui))) placeHandLine(view, ui, scrolled);
      put("actions", actionsHtml(view, advice, ui));
      put("first", "");
    } else {
      put("advice", ""); put("table", ""); put("line", ""); put("actions", "");
      // No table to draw. The first-run form is for a session that does not exist yet; when the program
      // answered with an error (or not at all) the page says that, and never offers a blank start by itself.
      put("first", ui.viewError ? viewErrorHtml(ui.viewError, mode) : firstRunHtml(mode, setup));
    }
    ["advice", "table", "line", "actions"].forEach((name) => { part(name).hidden = !view; });
    part("first").hidden = !!view;
    const toast = toastHtml(view, ui);
    sheetToast = ui.sheet ? toast : "";
    put("overlay", overlayHtml(view, advice, ui, mode));
    put("toast", ui.sheet ? "" : toast);
    app.inert = !!ui.sheet;                                   // a sheet is modal: the page behind it cannot be used

    moveFocus(ui, active, activeKey, typing);
    keepTyped(halfTyped);
    keepRefused(ui);
    fitStrip();
    noteBar();
  }

  /* The strip never cuts a value in half. Its widths are chosen so the usual numbers fit (app.css); when
     a row is too short all the same (six-digit blinds, five-digit fields), the parts that can be read
     elsewhere leave it one after the other, until the rest fits: the average stack (settings), the
     wordmark, the ante (the tooltip of the blinds), the places paid (settings; the pill counts from them). */
  const GIVE_WAY = ["no-avg", "no-word", "no-ante", "no-paid"];
  // The header's rules run across the whole window, also where the page is a column narrower than it.
  function bleed() {
    const app = document.getElementById("app");
    const side = Math.max(0, (document.documentElement.clientWidth - app.getBoundingClientRect().width) / 2);
    document.documentElement.style.setProperty("--bleed", side + "px");
  }
  function fitStrip() {
    bleed();
    const header = part("header");
    const strip = header.querySelector(".strip");
    GIVE_WAY.forEach((name) => header.classList.remove(name));
    if (!strip) return;
    // Too short: the last part reaches beyond the strip's own room.
    const tooShort = () => {
      const room = strip.getBoundingClientRect().right - (parseFloat(getComputedStyle(strip).paddingRight) || 0);
      return Array.prototype.some.call(strip.children, (kid) => kid.getClientRects().length && kid.getBoundingClientRect().right > room + 0.5);
    };
    for (let i = 0; i < GIVE_WAY.length && tooShort(); i++) header.classList.add(GIVE_WAY[i]);
  }

  // What is typed and not sent yet, in every field on the page: a menu or a sheet that is drawn anew
  // while it is open (a type was chosen, a refusal appeared) keeps it. A field is known by its name and
  // by what it sends, so a text typed for seat 4 never turns up in the menu of seat 5.
  function fieldId(field) {
    return field.dataset.fk + "|" + (field.dataset.emit || (field.form && field.form.dataset.emit) || "");
  }
  function typedFields() {
    const typed = {};
    Array.prototype.forEach.call(document.querySelectorAll("input[data-fk],textarea[data-fk]"), (field) => {
      if (field.dataset.dirty && !field.dataset.sent && !field.dataset.cancelled && field.type !== "checkbox") typed[fieldId(field)] = field.value;
    });
    return typed;
  }
  function keepTyped(typed) {
    if (!Object.keys(typed).length) return;
    Array.prototype.forEach.call(document.querySelectorAll("input[data-fk],textarea[data-fk]"), (field) => {
      const value = typed[fieldId(field)];
      if (value == null || field.dataset.dirty) return;
      field.value = value;
      markDirty(field);
    });
  }

  // The field whose value was refused was drawn anew (the refusal now stands under it): put the text back.
  function keepRefused(ui) {
    const error = ui.fieldError;
    if (!error || error.value == null) return;
    const field = document.querySelector('[data-fk="' + error.fk + '"]');
    if (!field || field.dataset.dirty || !("value" in field)) return;
    field.value = error.value;
    markDirty(field);
  }

  // Something was typed into this field: the Save button of its menu wakes up.
  function markDirty(field) {
    field.dataset.dirty = "1";
    const pop = field.closest(".pop");
    const save = pop && pop.querySelector("[data-save]");
    if (save) save.disabled = false;
  }

  // The hand line scrolls sideways. A step that was added is brought into sight (the line goes to its
  // end); a step that is selected is brought into sight; otherwise the line stays where it was.
  let lineWas = "";            // hand and number of steps at the last draw
  function placeHandLine(view, ui, scrolled) {
    const events = part("line").querySelector(".events");
    if (!events) { lineWas = ""; return; }
    const hand = view.hand;
    const now = hand ? hand.no + ":" + (hand.line || []).length : "";
    const grew = now !== lineWas;
    lineWas = now;
    events.scrollLeft = scrolled;
    const chip = ui.selected != null ? events.querySelector('[data-fk="event-' + ui.selected + '"]') : null;
    if (chip) {
      const box = events.getBoundingClientRect(), at = chip.getBoundingClientRect();
      if (at.left < box.left + 4) events.scrollLeft += at.left - box.left - 4;
      else if (at.right > box.right - 4) events.scrollLeft += at.right - box.right + 4;
    } else if (grew) {
      events.scrollLeft = events.scrollWidth;
    }
  }

  /* The 400 ms rule of the action bar. A pointer click on a bar button counts only when that button
     (the same word, for the same side: hero or an opponent) has been at that place for 400 ms. A
     double-click therefore records one action: the button that turns up under the pointer after the
     first click (Next hand where Follow was) is not pressed by the second. Keys are not affected. */
  const BAR_WAIT_MS = 400;
  let barSince = {};           // button and place -> when it was first there
  function barId(button) {
    const box = button.getBoundingClientRect();
    const label = button.querySelector(".label");
    const name = button.dataset.fk || (label ? label.textContent : button.textContent);
    // (its place on the page, not in the window: scrolling the page does not make a button a new one)
    return name + "@" + Math.round(box.left + window.scrollX) + "," + Math.round(box.top + window.scrollY) + "," + Math.round(box.width);
  }
  function noteBar() {
    const now = performance.now();
    const next = {};
    Array.prototype.forEach.call(part("actions").querySelectorAll("button"), (button) => {
      const id = barId(button);
      next[id] = barSince[id] != null ? barSince[id] : now;
    });
    barSince = next;
  }
  function barClickTooEarly(button) {
    const since = barSince[barId(button)];
    return since == null || performance.now() - since < BAR_WAIT_MS;
  }
  // Every button of the bar can be clicked now (for the browser checks).
  function barArmed() {
    noteBar();
    const now = performance.now();
    return Object.keys(barSince).every((id) => now - barSince[id] >= BAR_WAIT_MS);
  }

  function moveFocus(ui, active, activeKey, typing) {
    const openNow = openThing(ui);
    if (openNow !== openBefore) {
      if (openNow && !openBefore) opener = lastUsed;
      const closed = !openNow;
      openBefore = openNow;
      if (closed) {
        const back = findByKey(opener);
        opener = null;
        if (back) { back.focus(); return; }
      } else {
        const first = document.querySelector("#region-overlay [data-autofocus], #region-table .pop[data-autofocus], #region-table .pop [data-autofocus], " +
                                             "#region-line [data-autofocus], #region-actions [data-autofocus], #region-header [data-autofocus]") ||
                      document.querySelector("#region-table .pop button:not(:disabled)");
        if (first) {
          first.focus();
          if (first.select) first.select();                   // a default is pre-selected: typing overwrites it
          return;
        }
      }
    }
    // The control that had the focus was redrawn: give the focus to its new copy.
    if (active && active !== document.body && !document.body.contains(active)) {
      const again = findByKey(activeKey);
      if (again) {
        again.focus();
        if (typing && "value" in again) {
          again.value = typing.value;
          markDirty(again);
          try { again.setSelectionRange(typing.start, typing.end); } catch (error) { /* not a text field */ }
        }
      }
    }
  }

  // `field`: the field the value was typed into. It travels as detail.from = {fk, value}, so the
  // controller can keep that field open, with its text, when the server refuses the value.
  function send(detail, element, field) {
    if (!detail || !Object.keys(detail).length) return;
    if (element) lastUsed = focusKey(element);
    if (field && field.dataset && field.dataset.fk) detail.from = {fk: field.dataset.fk, value: field.value};
    document.dispatchEvent(new CustomEvent("menlo:event", {detail: detail}));
  }

  function readEmit(element) {
    try { return JSON.parse(element.dataset.emit); } catch (error) { return null; }
  }

  // What a field sends. An amount typed while the numbers are shown in big blinds: a bare number is
  // big blinds ("25" travels as "25bb"); one that was not touched travels as the exact chips it stood for.
  const BARE_NUMBER = /^\s*[+\-\u2212]?\d[\d,]*(?:[.,]\d+)?\s*$/;
  function fieldValue(field) {
    if (field.type === "checkbox") return field.checked;
    const value = field.value;
    if (field.dataset.unit !== "bb") return value;
    if (field.dataset.exact != null && value === field.dataset.exactText) return field.dataset.exact;
    return BARE_NUMBER.test(value) ? value.trim().replace("\u2212", "-") + "bb" : value;
  }
  // The value of a field, with the name it travels under.
  function withValue(detail, field) {
    const name = field.dataset.name || field.name || "text";
    detail[name] = fieldValue(field);
    return detail;
  }

  function isField(element) {
    return element.tagName === "INPUT" || element.tagName === "SELECT" || element.tagName === "TEXTAREA";
  }

  function onClick(event) {
    const save = event.target.closest("[data-save]");
    if (save && !save.disabled) { saveFields(save.closest(".pop")); return; }
    const element = event.target.closest("[data-emit]");
    if (!element || element.disabled) return;
    if (element.tagName === "FORM" || isField(element)) return;        // these send on Enter or on change
    // A pointer click (not Enter or Space on the button) on the action bar: the 400 ms rule.
    if (event.detail > 0 && element.tagName === "BUTTON" && element.closest("#region-actions") && barClickTooEarly(element)) return;
    send(readEmit(element), element);
  }

  // The Save button of a seat's menu: every field of the menu that was changed is sent, as Enter in it would.
  function saveFields(pop) {
    if (!pop) return;
    Array.prototype.forEach.call(pop.querySelectorAll("input[data-emit]"), (field) => {
      if (!field.dataset.dirty || field.value === field.defaultValue) return;
      field.dataset.sent = field.value;
      send(withValue(readEmit(field), field), field, field);
    });
  }

  function onSubmit(event) {
    const form = event.target;
    if (!form.dataset || !form.dataset.emit) return;
    event.preventDefault();
    const detail = readEmit(form);
    const into = form.dataset.into ? (detail[form.dataset.into] = {}) : detail;
    const changedOnly = form.dataset.changedOnly != null;      // the stack sweep: a stack left as it was is not sent
    for (let i = 0; i < form.elements.length; i++) {
      const field = form.elements[i];
      if (!field.name) continue;
      if (changedOnly && field.value === field.defaultValue) continue;
      into[field.name] = fieldValue(field);
    }
    if (changedOnly && !Object.keys(into).length) delete detail.op;    // nothing was typed: only close the sheet
    // The field a refusal is shown at: the one the form names, else the first one that was filled in.
    const from = form.dataset.from ? form.querySelector('[data-fk="' + form.dataset.from + '"]') : null;
    // data-hold: the form (a sheet) stays open until the server has taken what it sends; a refusal is said at its foot.
    if (detail.op && !from && form.dataset.hold != null) detail.from = {fk: "", value: ""};
    send(detail, form, detail.op ? from : null);
  }

  // A lone field sends on Enter, and when it is left after a change: a deliberate click elsewhere.
  // Not when Esc cancelled it, and never a field that is saved with Enter only (a seat's stack and name).
  function onChange(event) {
    const field = event.target;
    if (drawing || !isField(field) || !field.dataset.emit) return;
    if (field.dataset.cancelled || (field.dataset.enterOnly != null && field.tagName === "INPUT")) return;
    if (field.dataset.sent === field.value) return;                    // Enter already sent this value
    field.dataset.sent = field.value;
    send(withValue(readEmit(field), field), field, field);
  }

  function onInput(event) {
    const field = event.target;
    if (!isField(field)) return;
    markDirty(field);
    delete field.dataset.sent;
    delete field.dataset.cancelled;
    // The refusal under this field has been read: typing takes it away.
    if (field.getAttribute("aria-invalid") === "true") send({ui: {fieldError: null}}, null);
  }

  // Esc in a field: its first value comes back and nothing is sent, whatever closes the field afterwards.
  function cancelField(field) {
    if (!field || !isField(field)) return;
    if (field.tagName === "SELECT") {
      Array.prototype.forEach.call(field.options, (option) => { option.selected = option.defaultSelected; });
    } else if (field.type === "checkbox") {
      field.checked = field.defaultChecked;
    } else {
      field.value = field.defaultValue;
    }
    field.dataset.cancelled = "1";
    field.dataset.sent = field.value;
    delete field.dataset.dirty;
  }

  function onKeyDown(event) {
    const element = event.target;
    if (event.key === "Enter" && element.tagName === "INPUT" && element.dataset.emit && element.type !== "checkbox") {
      event.preventDefault();
      element.dataset.sent = element.value;
      delete element.dataset.cancelled;
      send(withValue(readEmit(element), element), element, element);
      return;
    }
    const arrows = {ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1};
    const step = arrows[event.key];
    if (!step || isField(element)) return;
    // Inside the tabs, the table and the hand line the arrows move between the items: one Tab stop each.
    const item = element.closest("[data-arrow]");
    const group = item && item.closest("[data-arrows]");
    if (!group) return;
    const items = Array.prototype.filter.call(group.querySelectorAll("[data-arrow]"), (el) => !el.disabled);
    const at = items.indexOf(item);
    if (at < 0) return;
    event.preventDefault();
    items[(at + step + items.length) % items.length].focus();
  }

  // How wide a thin scroll bar is in this browser: nothing where bars lie over the page (macOS, phones),
  // about 10px on Windows. The advice column keeps that much room free in the page's margin (app.css, --sbw).
  function measureScrollBar() {
    const probe = document.createElement("div");
    probe.style.cssText = "position:absolute;top:-99px;left:0;width:60px;height:30px;overflow-y:scroll;scrollbar-width:thin";
    document.body.appendChild(probe);
    const width = probe.offsetWidth - probe.clientWidth;
    probe.remove();
    document.documentElement.style.setProperty("--sbw", Math.max(0, Math.min(width, 14)) + "px");
  }

  let mounted = false;
  function mount() {
    if (mounted) return;
    mounted = true;
    measureScrollBar();
    window.addEventListener("resize", fitStrip);
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(fitStrip);
    document.addEventListener("click", onClick);
    document.addEventListener("submit", onSubmit);
    document.addEventListener("change", onChange);
    document.addEventListener("input", onInput);
    document.addEventListener("keydown", onKeyDown);
  }

  window.MenloUI = {
    mount: mount,
    render: render,
    closeTopPatch: closeTopPatch,
    cancelField: cancelField,
    format: {chips: fmtChips, short: fmtShort, stack: fmtStack, bb: fmtBb},
    SLOTS: SLOTS,
    CHOICES: CHOICES,
    // For the controller (controller.js): the same small rules the buttons use, so a key and a click do the same thing.
    pickerStep: pickerStep,
    freshPicker: freshPicker,
    wantSuits: wantSuits,
    isCurrent: isCurrent,
    actingSeat: actingSeat,
    roundKey: roundKey,
    plainAmount: plainAmount,
    typesBb: typesBb,
    heroOutOfHand: heroOutOfHand,
    heroOutOfChips: heroOutOfChips,
    eventHasAmount: eventHasAmount,
    barArmed: barArmed,
    buttonRule: buttonRule,
    MOVES_WORDS: MOVES_WORDS,
    seatOf: seatOf,
    spinOver: spinOver,
    seatClick: seatClick,
    only: only,
    AFTER_ACT: AFTER_ACT,
    NOTICE: NOTICE,
  };
})();
