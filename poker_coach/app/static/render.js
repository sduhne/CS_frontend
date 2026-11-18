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
       cmd   a job for the browser: "copy" (with text)
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
     set_config      key, value                                       style, plan, opponents, unit, deck
     set_ante_kind   kind: none | player | bb                         settings
     set_ladder      text (one level per line), or name               settings
     set_size        size                                             table tools
     button_step     step: -1 | 1                                     table tools
     new_table                                                        table tools
     set_button      seat                                             seat menu
     seat_player     seat, stack (text), name                         an empty seat
     set_stack       seat, text                                       seat menu
     set_stacks      stacks: {"2": "12.5k", "3": ""}                  the all-stacks sheet (blank keeps)
     rename          seat, name                                       seat menu
     set_type        seat, type                                       seat menu
     note            seat, text                                       seat menu
     set_status      seat, status: active | away                      seat menu
     bust, clear_seat  seat                                           seat menu
     deal                                                             New hand, Next hand
     set_cards       slot: hero | flop | turn | river, text           the card picker ("AhKd", "AKs", "Ks7d2c", "Th")
     act             seat, kind: fold | check | call | bet | raise | allin,
                     to (a number from a preset or from Follow, text from the amount field),
                     via: "follow" when the Follow button sent it     the action bar
     close_round                                                      Rest fold, Skip the board
     edit_event      index, to (text)                                 a selected event on the hand line
     remove_event    index                                            a selected event on the hand line
     award           ranking: [[seat], [seat, seat]]                  the result bar, the seat menu
     skip_hand, discard_hand                                          the bars, table tools
     new_session     mode, and the fields of the form beside it:      first run, New tournament
                     size, level, start_stack, hero_stack, entrants,
                     remaining, paid, buyin (text; blank = not given)
     new_game        start_stack: 300 | 500                           Spin, between hands

   UI STATE (every key is optional)
     panel        "why" | "range"        which advice tab shows where only one fits
     sheet        null | "settings" | "why" | "keys" | "history" | "new" | "stacks"
     seatMenu     null | seat number      the seat whose menu is open
     menu         null | "table"          the table tools menu
     picker       null | {slot, cards: [], rank: null, rank2: null}    the card picker and how far it is
     pickerOff    true once the user closed the picker himself: the controller then does not reopen it
                  by itself until the table asks for other cards
     amount       null | {kind: "bet" | "raise", seat, text}           the amount row is open
     selected     null | index of the selected event on the hand line
     edit         null | "level" | "remaining" | "paid" | "avg_stack"  the strip value being typed
     target       null | seat             record the next action for this seat, not view.hand.target
     awardTiers   [[seat], ...]           winners already chosen when a side pot needs another
     setupMode    "tournament" | "spin" | "aof"    the form shown on first run
     toast        {text, fix, undo} | null         shown instead of view.toast; null hides both

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
    9: [["B", 50], ["B", 11], ["L", 60], ["L", 34], ["T", 35], ["T", 65], ["R", 34], ["R", 60], ["B", 89]],
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
      {value: "full", label: "Full"},
      {value: "allin", label: "All-in or fold"},
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
    deck: [{value: "one-ink", label: "One ink"}, {value: "four-colour", label: "Four colours"}],
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
                 "In All-In or Fold, during a hand, the digit alone is that player's all-in (again takes it back)"],
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
  const ALL_CLOSED = {seatMenu: null, menu: null, picker: null, amount: null, selected: null, edit: null};
  function only(patch) { return Object.assign({}, ALL_CLOSED, patch); }
  // After an action is recorded the bar goes back to the server's next player.
  const AFTER_ACT = {amount: null, target: null, seatMenu: null, selected: null};

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
  // What goes into an amount field: digits only, so it can be edited.
  function plainAmount(view, chips) {
    if (chips == null) return "";
    return isAof(view) ? fmtBb(chips) : String(chips);
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

  // The seat the action bar records for: the one the user aimed at, else the server's next player.
  function actingSeat(view, ui) {
    if (!view.hand || view.hand.needs !== "action") return null;
    return ui.target != null ? ui.target : view.hand.target;
  }
  function heroToAct(view) {
    return !!(view.hand && view.hand.needs === "action" && view.hand.target_is_hero);
  }

  /* ---------- 3. Header and strip ---------- */

  const MARK = '<svg class="mark" viewBox="0 0 40 40" role="img" aria-label="Menlo Bet"><rect width="40" height="40" rx="9" fill="#FFD60A"/>' +
               '<path d="M8 30V11l12 11 12-11v19h-5V22l-7 6.5L13 22v8z" fill="#0A0A0B"/></svg>';

  function headerHtml(view, ui, mode) {
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
      ${toolsHtml(view)}`;
  }

  function toolsHtml(view) {
    const can = (view && view.can) || {};
    const undo = `<button class="tool" aria-label="Undo" title="Undo"${can.undo ? "" : " disabled"}${emit({op: "undo"})}>${icon("undo")}</button>`;
    const redo = can.redo ? `<button class="tool" aria-label="Redo" title="Redo"${emit({op: "redo"})}>${icon("redo")}</button>` : "";
    const menu = `<button class="tool" aria-label="Menu and settings" title="Menu"${emit({ui: only({sheet: "settings"})})}>${icon("menu")}</button>`;
    return `<div class="tools">${view ? undo + redo : ""}${menu}</div>`;
  }

  function stripHtml(view, ui) {
    let parts;
    if (view.mode === "spin") parts = [levelStat(view, ui), opponentsStat(view), spinTally(view)];
    else if (view.mode === "aof") parts = [aofBlinds(view), opponentsStat(view), aofTally(view)];
    else parts = [levelStat(view, ui), leftStat(view, ui), paidStat(view, ui), stagePill(view), averageStat(view, ui), styleStat(view)];
    return `<div class="strip">${parts.join("")}</div>`;
  }

  function stepper(sign, label, detail, due) {
    return `<button class="step${due ? " due" : ""}" aria-label="${esc(label)}" title="${esc(label)}"${emit(detail)}>${sign}</button>`;
  }

  // A value in the strip: a button that shows it, or the field that replaces it while it is typed.
  function stripValue(ui, name, opts) {
    if (ui.edit === name) {
      return `<input class="in${opts.short ? " short" : ""}" value="${esc(opts.typed)}" autocomplete="off" spellcheck="false"
        aria-label="${esc(opts.fieldLabel)}" data-fk="edit-${name}" data-autofocus data-name="text"${emit(opts.send)}>`;
    }
    return `<button class="value" aria-label="${esc(opts.label)}. Change" data-fk="value-${name}"${emit({ui: only({edit: name})})}>
        <span class="eyebrow">${esc(opts.eyebrow)}</span>${opts.shown}</button>`;
  }
  function unset() { return '<span class="unset">Set</span>'; }

  function blindsText(level) {
    if (!level || level.bb == null) return "?";
    return `${fmtShort(level.sb)} / ${fmtShort(level.bb)}`;
  }
  function anteText(level) {
    if (!level || !level.ante || level.ante_kind === "none") return "no ante";
    return level.ante_kind === "bb" ? `BB ante ${fmtShort(level.ante)}` : `ante ${fmtShort(level.ante)}`;
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
    return `<div class="stat">${stepper(MINUS, "Blinds down", {op: "level_down"})}${value}` +
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
    return `<div class="stat">` + stripValue(ui, "paid", {
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

  function labelOf(choices, value) {
    const found = choices.find((choice) => choice.value === value);
    return found ? found.label : String(value || "");
  }
  function nextOf(choices, value) {
    const at = choices.findIndex((choice) => choice.value === value);
    return choices[(at + 1) % choices.length].value;
  }

  // One click moves to the next style.
  function styleStat(view) {
    const style = view.strip.style;
    const next = nextOf(CHOICES.style, style);
    return `<div class="stat from-style"><button class="value" aria-label="Style: ${esc(labelOf(CHOICES.style, style))}. Change"` +
           `${emit({op: "set_config", key: "style", value: next})}><span class="eyebrow">Style</span>` +
           `<span class="text">${esc(labelOf(CHOICES.style, style))}</span></button></div>`;
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
  function slabContent(view, advice) {
    if (isCurrent(view, advice)) {
      const h = advice.headline;
      return {tone: h.tone || "wait", eyebrow: heroToAct(view) ? "Your turn" : "Coach", verb: h.verb, size: h.size_text,
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
    // Once the hand is settled the slab says who won what; otherwise the coach's own line on what it waits for.
    const settled = !!(view.hand && view.hand.needs === "next");
    const spot = settled ? waiting.text : (fresh && advice.spot) || waiting.text;
    return {tone: "wait", eyebrow: "Coach", verb: waiting.verb, spot: spot, live: false};
  }

  // Long verbs get a smaller size so they stay on the slab.
  function verbClass(verb) {
    const length = String(verb || "").length;
    return length >= 10 ? " xlong" : length >= 8 ? " long" : "";
  }

  // How sure: three bars filled is clear, two standard, one close.
  const SURE_BARS = {clear: 3, standard: 2, close: 1};
  function sureHtml(sure) {
    const filled = SURE_BARS[sure];
    if (!filled) return "";
    const bars = [1, 2, 3].map((n) => `<i${n <= filled ? ' class="on"' : ""}></i>`).join("");
    return `<span class="sure eyebrow"><span class="pips" aria-hidden="true">${bars}</span>${esc(sure)}</span>`;
  }

  function slabHtml(content) {
    return `<div class="slab ${esc(content.tone)}">
      <div class="head"><span class="eyebrow">${esc(content.eyebrow)}</span>${content.live ? sureHtml(content.sure) : ""}</div>
      <div class="act"><span class="verb${verbClass(content.verb)}">${esc(content.verb)}</span>
        ${content.size ? `<span class="size">${esc(content.size)}</span>` : ""}
        ${content.qualifier ? `<span class="pill">${esc(content.qualifier)}</span>` : ""}</div>
      ${content.spot ? `<div class="spot">${prose(content.spot)}</div>` : ""}
    </div>`;
  }

  function tileHtml(tile) {
    const look = tile.sign > 0 ? " win" : tile.sign < 0 ? " loss" : "";
    const length = String(tile.value || "").length;
    const fit = length > 11 ? " xlong" : length > 7 ? " long" : "";
    return `<div class="tile"><div class="eyebrow">${esc(tile.label)}</div>
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
    const content = slabContent(view, advice);
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
    return {panel: panel, html: slabHtml(content) + whyline + tabs + why + chart + where};
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

  function tableHtml(view, ui) {
    const table = view.table;
    const slots = SLOTS[table.size] || SLOTS[9];
    let pods = "", chips = "", dealer = "";
    (table.seats || []).forEach((seat) => {
      const slot = slots[seat.seat - 1];
      if (!slot) return;
      pods += podHtml(view, ui, seat, slot);
      chips += chipHtml(view, seat, slot);
      if (seat.seat === table.button) dealer = `<span class="deal" style="${dealerPlace(slot, seat.is_hero)}" aria-hidden="true">D</span>`;
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

  // The stack line of a pod: the amount in the chosen unit, then the other unit where there is room.
  function stackHtml(view, seat) {
    if (seat.all_in) return '<span class="stack"><span class="num">ALL-IN</span></span>';
    // A player sitting out, or one with no chips left, shows the word; the stack keeps its place where there is room.
    const word = {away: "Away", busted: "Out"}[seat.status];
    let number, unit = "";
    if (showsBb(view)) {
      number = fmtBb(isAof(view) ? seat.stack : seat.stack_bb, true);
      unit = "<u>bb</u>";
    } else {
      number = fmtStack(seat.stack);
    }
    if (seat.stale) number = "~" + number;      // a stack nobody has confirmed since a hand that was not recorded
    const other = word ? `<span class="tag">${word}</span>`
      : `<span class="other">${otherText(view, seat.stack, seat.stack_bb)}</span>`;
    return `<span class="stack"><span class="num">${number}</span>${unit}${other}</span>`;
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
    const aimed = ui.target != null ? seat.seat === ui.target : !!seat.is_target;
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
        aria-label="Seat ${seat.seat}, empty. Add a player"${emit(seatClick(view, seat))}>+ Seat</button>`;
    }
    const state = podState(view, ui, seat);
    const words = podWords(view, seat, state);
    const title = seat.note ? ` title="${esc(seatName(seat) + ": " + seat.note)}"` : "";
    if (seat.is_hero) return heroPodHtml(view, ui, seat, place, state, words);
    const type = seat.type && seat.type !== "unknown" ? ` \u00b7 ${esc(seat.type)}` : "";
    return `<button class="${state.cls}" style="${place}" data-seat="${seat.seat}" data-arrow tabindex="-1" aria-label="${esc(words)}"${title}${emit(seatClick(view, seat))}>
      <span class="top"><span class="pos">${esc(seat.pos || "\u2013")}</span><span class="key">${seat.seat}</span></span>
      ${stackHtml(view, seat)}
      <span class="name">${esc(seat.name || `Seat ${seat.seat}`)}${type}</span>
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
    const pick = view.hand ? emit({ui: only({picker: freshPicker("hero")})}) : emit(seatClick(view, seat));
    return `<div class="${state.cls}" style="${place}" data-seat="${seat.seat}">
      <button class="hand" data-arrow tabindex="0" data-fk="hero-cards" aria-label="Your cards: ${esc(cards.words)}. Change"${pick}>${cards.html}</button>
      <button class="info" data-arrow tabindex="-1" data-fk="hero-info" aria-label="${esc(words)}"${emit(seatClick(view, seat))}>
        <span class="top"><span class="pos">${esc(seat.pos || "\u2013")}</span><span class="pill you">You</span></span>
        ${stackHtml(view, seat)}
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
    return `<div class="centre">
      <div class="pot"><span class="eyebrow">Pot</span><span class="num">${mainText(view, hand.pot, hand.pot_bb)}</span>${other ? `<small>${other}</small>` : ""}</div>
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
    if (!events.length) return `<span class="hint">The hand will be written here, one chip per step.</span>`;
    const last = events.length - 1;
    const chips = list(events, (event, at) => {
      const selected = ui.selected === event.i;
      return `<button class="evb" data-arrow tabindex="${at === last ? 0 : -1}" aria-pressed="${selected}" data-fk="event-${event.i}"` +
             `${emit({ui: only({selected: selected ? null : event.i})})}>${eventHtml(event, selected)}</button>`;
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
    const typed = amount.text != null ? amount.text : plainAmount(view, legal.default);
    const player = seatOf(view, seat);
    // Whose bet it is stands on the action bar ("Recording"); the field only says what the number is.
    const who = player && !player.is_hero ? `${seatTitle(player)}: ` : "";
    const label = amount.kind === "bet" ? "Bet" : "Raise to";
    const presets = forTarget ? list(hand.presets, (preset) =>
      `<button type="button" class="preset"${emit({op: "act", seat: seat, kind: amount.kind, to: preset.to, ui: AFTER_ACT})}>${esc(preset.label)}</button>`) : "";
    return `<form class="amount"${emit({op: "act", seat: seat, kind: amount.kind, ui: AFTER_ACT})}>
      <label class="field"><span class="eyebrow">${esc(label)}</span>
        <input name="to" value="${esc(typed)}" inputmode="decimal" autocomplete="off" spellcheck="false" data-fk="amount" data-autofocus
          aria-label="${esc(who + label)}"${forTarget ? "" : ' placeholder="usual size"'}></label>
      <div class="presets">${presets}</div>
      <button type="submit" class="btn compact">OK ${keycap("Enter")}</button>
      <button type="button" class="tool" aria-label="Cancel" title="Cancel"${emit({ui: {amount: null}})}>${icon("close")}</button>
    </form>`;
  }

  /* ---------- 7. Action bar ---------- */

  // A button of the bar: the word with its key, and under it the amount when there is one.
  function barButton(opts) {
    const cls = "btn" + (opts.primary ? " primary" : "") + (opts.wide ? " wide" : "");
    const key = opts.key ? keycap(opts.key) : "";
    const sub = opts.sub ? `<span class="sub">${opts.sub}</span>` : "";
    return `<button class="${cls}"${opts.fk ? ` data-fk="${opts.fk}"` : ""}${opts.off ? " disabled" : ""}${emit(opts.send)}>` +
           `<span class="label">${esc(opts.label)}${key}</span>${sub}</button>`;
  }
  function aboutBlock(eyebrow, text) {
    return `<div class="about"><span class="eyebrow">${esc(eyebrow)}</span><span class="who">${esc(text)}</span></div>`;
  }

  function actionsHtml(view, advice, ui) {
    const hand = view.hand;
    if (!hand) return betweenHandsBar(view);
    const selected = ui.selected != null ? (hand.line || []).find((event) => event.i === ui.selected) : null;
    if (selected) return eventBar(view, selected);
    if (hand.needs === "cards") return cardsBar();
    if (hand.needs === "board") return boardBar(hand);
    if (hand.needs === "result") return resultBar(view, ui);
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

  function betweenHandsBar(view) {
    if (spinOver(view)) return newGameButtons(true);
    return barButton({label: "New hand", key: "N", primary: true, wide: true, fk: "deal", send: {op: "deal"}}) +
           barButton({label: "Skip a hand", sub: "the button moves on", send: {op: "skip_hand"}}) +
           (view.mode === "spin" ? newGameButtons(false) : "");
  }

  function cardsBar() {
    return barButton({label: "Pick your cards", wide: true, fk: "pick",
                      send: {ui: only({picker: freshPicker("hero"), pickerOff: false})}}) +
           barButton({label: "Discard hand", send: {op: "discard_hand"}});
  }

  function boardBar(hand) {
    const count = (hand.board || []).length;
    const slot = count < 3 ? "flop" : count === 3 ? "turn" : "river";
    // Skipping a street gives everybody still to act a check. While the action is on hero that would
    // be his check too, so the button waits until he has acted (or is all-in, or out of the hand).
    return barButton({label: `Pick the ${slot}`, wide: true, fk: "pick",
                      send: {ui: only({picker: freshPicker(slot), pickerOff: false})}}) +
           barButton({label: "Skip the board", key: "Enter", off: !!hand.target_is_hero, send: {op: "close_round"}});
  }

  // Who won. Each player still in gets a button; a side pot asks again for the next best hand.
  function resultBar(view, ui) {
    const tiers = ui.awardTiers || [];
    const ranked = [].concat.apply([], tiers);
    const live = (view.table.seats || []).filter((seat) => !seat.empty && seat.in_hand && !seat.folded && ranked.indexOf(seat.seat) < 0);
    const hero = live.find((seat) => seat.is_hero);
    const others = live.filter((seat) => !seat.is_hero);
    const award = (seats) => ({op: "award", ranking: tiers.concat([seats]), ui: {seatMenu: null}});
    let buttons = "";
    if (hero) buttons += barButton({label: "You won", key: "W", send: award([hero.seat])});
    if (hero && others.length === 1) {
      buttons += barButton({label: "You lost", key: "L", send: award([others[0].seat])});
    } else {
      buttons += list(others.slice(0, 4), (seat) => barButton({label: `${seat.pos || seatName(seat)} won`, sub: esc(seatName(seat)), send: award([seat.seat])}));
    }
    if (live.length > 1) buttons += barButton({label: "Split", send: award(live.map((seat) => seat.seat))});
    return aboutBlock(tiers.length ? "Side pot" : "Showdown", tiers.length ? "Next best hand?" : "Who won?") + buttons;
  }

  function nextBar(view) {
    if (spinOver(view)) return newGameButtons(true);
    return barButton({label: "Next hand", key: "N", primary: true, wide: true, fk: "deal", send: {op: "deal"}});
  }

  // What the Follow button will do, in words.
  function followText(view, follow) {
    if (!follow) return "";
    const kind = follow.kind === "allin" ? "all-in" : follow.kind;
    if (follow.to == null || follow.kind === "allin") return kind;
    return `${kind} ${chipsOnlyText(view, follow.to)}`;
  }

  // The bar while a player has to act: hero (Follow first), or the player being recorded.
  function actBar(view, advice, ui) {
    const hand = view.hand;
    const seat = actingSeat(view, ui);
    const player = seatOf(view, seat);
    const isHero = !!(player && player.is_hero);
    const known = seat === hand.target;              // the legal moves in the view are for the server's next player
    const legal = hand.legal || {};
    const act = (kind) => ({op: "act", seat: seat, kind: kind, ui: AFTER_ACT});
    const ask = (kind) => ({ui: {amount: {kind: kind, seat: seat}, seatMenu: null, selected: null}});
    const can = (move) => !known || (legal[move] != null && legal[move] !== false);

    let first;
    if (isHero && known) {
      const follow = isCurrent(view, advice) ? advice.headline.follow : null;
      first = barButton({label: "Follow", key: "Space", primary: true, wide: true, fk: "follow", off: !follow,
                         sub: esc(followText(view, follow)),
                         send: follow ? Object.assign({op: "act", seat: seat, via: "follow", ui: AFTER_ACT}, follow) : {}});
    } else if (known) {
      const free = !hand.to_call;
      first = barButton({label: free ? "Rest check" : "Rest fold", key: "Enter", wide: true, fk: "rest",
                         sub: esc(player ? `next: ${seatTitle(player)}` : ""), send: {op: "close_round"}});
    } else {
      first = aboutBlock("Recording", player ? seatTitle(player) : `Seat ${seat}`);
    }

    const fold = barButton({label: "Fold", key: "F", off: !can("fold"), send: act("fold")});
    const callSub = known && legal.call != null ? esc(mainText(view, legal.call, hand.to_call_bb)) : "";
    const passive = known && legal.check
      ? barButton({label: "Check", key: "X", send: act("check")})
      : barButton({label: "Call", key: "C", sub: callSub, off: !can("call"), send: act("call")});
    const betting = known ? !!legal.bet : !hand.to_call;
    const raise = betting
      ? barButton({label: "Bet", key: "B", off: !can("bet"), send: ask("bet")})
      : barButton({label: "Raise", key: "R", off: !can("raise"), send: ask("raise")});
    const allinSub = known && legal.allin != null ? esc(chipsOnlyText(view, legal.allin, true)) : "";
    const allin = barButton({label: "All-in", key: "A", sub: allinSub, off: !can("allin"), send: act("allin")});

    // All-In or Fold has two moves. A call of an all-in is an all-in.
    if (isAof(view)) {
      const shove = known && legal.call != null
        ? barButton({label: "Call", key: "C", sub: callSub, send: act("call")})
        : allin;
      return first + shove + fold;
    }
    return first + fold + passive + raise + allin;
  }

  // A selected event on the hand line: change its amount, change its cards, or delete it.
  function eventBar(view, event) {
    const done = barButton({label: "Done", key: "Esc", send: {ui: {selected: null}}});
    if (isCardRun(event.text) || event.kind === "cards" || event.kind === "board") {
      // The first board event is the flop, then the turn, then the river (the event says so when the server names its street).
      const before = (view.hand.line || []).filter((other) => other.kind === "board" && other.i < event.i).length;
      const street = ["flop", "turn", "river"].indexOf(event.street) >= 0 ? event.street : ["flop", "turn", "river"][before] || "flop";
      const slot = event.kind === "board" ? street : "hero";
      return aboutBlock("Selected", "Cards") +
             barButton({label: "Change the cards", wide: true, send: {ui: only({picker: freshPicker(slot)})}}) + done;
    }
    const hasAmount = event.to != null && ["bet", "raise", "call", "allin"].indexOf(event.verb) >= 0;
    const edit = hasAmount
      ? `<form class="amount"${emit({op: "edit_event", index: event.i, ui: {selected: null}})}>
          <label class="field"><span class="eyebrow">Amount</span>
            <input name="to" value="${esc(plainAmount(view, event.to))}" inputmode="decimal" autocomplete="off" data-fk="event-amount" data-autofocus></label>
          <button type="submit" class="btn compact">Save ${keycap("Enter")}</button></form>`
      : aboutBlock("Selected", event.text);
    // An action nobody typed (a fold that follows from a later action) cannot be deleted, only changed.
    return edit + barButton({label: "Delete", key: "Del", off: !!event.auto, send: {op: "remove_event", index: event.i, ui: {selected: null}}}) + done;
  }

  /* ---------- 8. Menus on the table: a seat, the cards, the table tools ---------- */

  function tableMenus(view, ui) {
    if (ui.picker && view.hand) return pickerHtml(view, ui.picker);
    if (ui.seatMenu != null) {
      const seat = seatOf(view, ui.seatMenu);
      if (seat) return seat.empty ? addPlayerHtml(view, seat) : seatMenuHtml(view, ui, seat);
    }
    if (ui.menu === "table") return tableMenuHtml(view);
    return "";
  }

  function popHead(title, small, closePatch) {
    return `<div class="pop-head"><h2>${esc(title)}${small ? `<small>${esc(small)}</small>` : ""}</h2>
      <button type="button" class="tool" aria-label="Close" title="Close"${emit({ui: closePatch})}>${icon("close")}</button></div>`;
  }

  // A labelled field that sends its text on Enter (or when it is left after a change).
  function fieldHtml(opts) {
    return `<label class="field"><span class="eyebrow">${esc(opts.label)}</span>
      <input class="${opts.words ? "words" : ""}" value="${esc(opts.value == null ? "" : opts.value)}" data-name="${opts.name || "text"}" data-fk="${esc(opts.fk)}"
        ${opts.focus ? "data-autofocus" : ""} ${opts.placeholder ? `placeholder="${esc(opts.placeholder)}"` : ""} autocomplete="off" spellcheck="false"${emit(opts.send)}></label>`;
  }

  function seatMenuHtml(view, ui, seat) {
    const n = seat.seat;
    const closed = {seatMenu: null, target: null};
    const stack = fieldHtml({label: "Stack", value: plainAmount(view, seat.stack), fk: "seat-stack", focus: true, send: {op: "set_stack", seat: n}});
    const away = seat.status === "away";
    const sit = `<button class="menu-btn"${emit({op: "set_status", seat: n, status: away ? "active" : "away"})}>${away ? "Sit back" : "Sit out"} ${keycap("O")}</button>`;
    const button = `<button class="menu-btn"${seat.is_button ? " disabled" : ""}${emit({op: "set_button", seat: n})}>Button ${keycap("D")}</button>`;
    // At a showdown the menu can also name this player the winner.
    const showdown = view.hand && view.hand.needs === "result" && seat.in_hand && !seat.folded;
    const won = showdown
      ? `<div class="row"><button class="menu-btn"${emit({op: "award", ranking: (ui.awardTiers || []).concat([[n]]), ui: closed})}>Won the pot ${keycap("W")}</button></div>`
      : "";
    if (seat.is_hero) {
      return `<div class="pop" role="dialog" aria-label="Your seat">
        ${popHead(seatTitle(seat), `seat ${n}`, closed)}${won}
        ${stack}
        <div class="row">${sit}${button}</div>
      </div>`;
    }
    const types = list(CHOICES.type, (type) => `<option value="${type}"${type === (seat.type || "unknown") ? " selected" : ""}>${type}</option>`);
    return `<div class="pop" role="dialog" aria-label="Seat ${n}">
      ${popHead(seatTitle(seat), `seat ${n}`, closed)}${won}
      <div class="two">${stack}
        ${fieldHtml({label: "Name", value: seat.name, words: true, name: "name", fk: "seat-name", send: {op: "rename", seat: n}})}
        <label class="field"><span class="eyebrow">Type</span><select data-name="type" data-fk="seat-type"${emit({op: "set_type", seat: n})}>${types}</select></label>
        ${fieldHtml({label: "Note", value: seat.note, words: true, fk: "seat-note", send: {op: "note", seat: n}})}
      </div>
      <div class="row">${sit}${button}
        <button class="menu-btn"${emit({op: "bust", seat: n, ui: closed})}>Bust ${keycap("K")}</button>
        <button class="menu-btn"${emit({op: "clear_seat", seat: n, ui: closed})}>Clear ${keycap("Del")}</button></div>
    </div>`;
  }

  function addPlayerHtml(view, seat) {
    const closed = {seatMenu: null, target: null};
    // The likeliest stack for a newcomer: the starting stack (All-In or Fold: the 8bb cap).
    const likely = isAof(view) ? "8" : plainAmount(view, view.strip && view.strip.start_stack);
    return `<form class="pop" role="dialog" aria-label="Add a player to seat ${seat.seat}"${emit({op: "seat_player", seat: seat.seat, ui: closed})}>
      ${popHead("Add a player", `seat ${seat.seat}`, closed)}
      <div class="two">
        <label class="field"><span class="eyebrow">Stack</span><input name="stack" value="${esc(likely)}" autocomplete="off" data-fk="add-stack" data-autofocus></label>
        <label class="field"><span class="eyebrow">Name</span><input class="words" name="name" placeholder="optional" autocomplete="off" data-fk="add-name"></label>
      </div>
      <div class="row"><button type="submit" class="menu-btn">Seat the player ${keycap("Enter")}</button></div>
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
        <button class="menu-btn"${emit({op: "button_step", step: 1})}>Button on ${keycap("]")}</button>
      </div>
      ${sizeRow}
      <div class="row">
        <button class="menu-btn"${emit({ui: only({sheet: "stacks"})})}>Every stack</button>
        ${view.mode === "tournament" ? `<button class="menu-btn"${emit({op: "new_table", ui: closed})}>New table</button>` : ""}
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
  function freshPicker(slot) { return {slot: slot, cards: [], rank: null, rank2: null}; }
  function cardsNeeded(slot) { return slot === "flop" ? 3 : slot === "hero" ? 2 : 1; }

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
    const state = (next) => ({ui: {picker: Object.assign(freshPicker(slot), {cards: cards}, next)}});
    const done = (text) => ({op: "set_cards", slot: slot, text: text, ui: {picker: null, selected: null}});

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

  function overlayHtml(view, advice, ui) {
    if (!view) return ui.sheet === "keys" ? sheetHtml("Keys", keysBody()) : ui.sheet === "settings" ? sheetHtml("Menu", firstRunMenu(), true) : "";
    if (ui.sheet === "settings") return sheetHtml("Settings", settingsBody(view), true);
    if (ui.sheet === "why") return sheetHtml("Why and range", whyBody(view, advice));
    if (ui.sheet === "keys") return sheetHtml("Keys", keysBody());
    if (ui.sheet === "history") return sheetHtml("Hand history", historyBody(view));
    if (ui.sheet === "new") return sheetHtml(view.mode === "tournament" ? "New tournament" : "New game", setupForm(view.mode, view.setup));
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
    const body = whyHtml(advice, live) + (live ? chartHtml(advice.chart) : "") + contextHtml(advice);
    return body || `<p class="empty-note">Nothing to explain yet.</p>`;
  }

  function section(title, body) { return `<div class="section"><h3>${esc(title)}</h3>${body}</div>`; }
  function choiceRow(label, choices, current, send) {
    return `<div class="choice"><span>${esc(label)}</span>${choiceHtml(label, choices, current, send)}</div>`;
  }
  function checkHtml(label, on, send) {
    return `<label class="check"><input type="checkbox"${on ? " checked" : ""} data-name="value"${emit(send)}><span>${esc(label)}</span></label>`;
  }

  const ICM_WORDS = {
    off: "ICM is off: the coach counts chips. Enter players left and places paid.",
    estimated: "ICM is estimated from typical payouts. Enter the smallest prize and the final-table prizes for the exact ladder.",
    on: "ICM is on, with typical payouts.",
    exact: "ICM is exact: the real prize ladder is in.",
  };

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

  function settingsBody(view) {
    const strip = view.strip || {};
    const config = (key) => (value) => ({op: "set_config", key: key, value: value});
    const tourney = (label, field, value, opts) => fieldHtml(Object.assign(
      {label: label, value: value, fk: "set-" + field, send: {op: "set_tournament", field: field}}, opts || {}));
    let html = `<p class="notice">${NOTICE}</p>`;

    if (view.mode === "tournament") {
      html += section("Tournament", `<div class="cols">
          ${fieldHtml({label: "Left", value: strip.remaining, fk: "set-remaining", send: {op: "remaining"}})}
          ${tourney("Paid", "paid", strip.paid)}
          ${tourney("Entrants", "entrants", strip.entrants)}
          ${tourney("Start stack", "start_stack", strip.start_stack)}
          ${tourney("Average", "avg_stack", strip.avg_stack)}
          ${tourney("Buy-in", "buyin", strip.buyin)}
        </div>
        ${tourney("Payouts", "payouts", payoutsText(strip), {words: true, placeholder: "auto, or 1:1000 2:600 4-6:200"})}
        <p class="hint">${esc(ICM_WORDS[strip.icm] || "")}</p>
        ${checkHtml("Re-entry is still open", strip.reentry_open, {op: "set_tournament", field: "reentry_open"})}
        ${checkHtml("Bounty tournament", strip.bounty, {op: "set_tournament", field: "bounty"})}`);
      html += section("Coach",
        choiceRow("Style", CHOICES.style, strip.style, config("style")) +
        choiceRow("Plan", CHOICES.plan, strip.plan, config("plan")) +
        choiceRow("Opponents", CHOICES.opponents.tournament, strip.opponents, config("opponents")));
    } else {
      html += section("Coach", choiceRow("Opponents", CHOICES.opponents[view.mode], strip.opponents, config("opponents")));
    }

    if (view.mode !== "aof") {
      const level = strip.level || {};
      const settings = view.settings || {};
      // The ladders the server knows, as an either-or; the levels of the one in use, ready to be edited.
      const ladders = (settings.ladders || []).map((ladder) => ({value: ladder.name, label: ladder.label || ladder.name}));
      const presets = ladders.length ? choiceRow("Ladder", ladders, settings.ladder, (name) => ({op: "set_ladder", name: name})) : "";
      const levels = settings.ladder_text != null ? settings.ladder_text
        : (settings.levels || []).map((level) => level.filter((part, at) => at < 2 || part).join("/")).join("\n");
      html += section("Blinds",
        choiceRow("Ante", CHOICES.ante_kind, level.ante_kind || "none", (kind) => ({op: "set_ante_kind", kind: kind})) +
        presets +
        `<form class="stacked"${emit({op: "set_ladder"})}><textarea class="in" name="text" aria-label="Blind ladder, one level per line"
            placeholder="A ladder of your own, one level per line:&#10;100/200/25&#10;150/300/40">${esc(levels)}</textarea>
          <div class="buttons"><button type="submit" class="btn compact">Use this ladder</button></div></form>`);
    }

    html += section("Screen",
      (view.mode === "aof" ? "" : choiceRow("Numbers in", CHOICES.unit, view.unit, config("unit"))) +
      choiceRow("Cards", CHOICES.deck, view.deck || "one-ink", config("deck")));
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

  function historyBody(view) {
    const hands = view.history || [];
    if (!hands.length) return `<p class="empty-note">No hands yet. Each hand lands here with what the coach said and what you did.</p>`;
    const rows = list(hands, (hand) => {
      const cards = isCardRun(hand.cards) ? cardsInline(hand.cards) : esc(hand.cards || "");
      const look = hand.net > 0 ? " win" : hand.net < 0 ? " loss" : "";
      const net = hand.net ? plus(hand.net, chipsOnlyText(view, hand.net)) : "0";
      return `<div class="hrow"><span class="num">${esc(hand.no)}</span><b>${cards}</b><span>${esc(hand.pos || "")}</span>
        <span>${hand.skipped ? "not recorded" : `coach <b>${esc(hand.advice || "none")}</b>, you <b>${esc(didWord(hand.did))}</b>`}${hand.deviated ? ' <span class="pill near">deviated</span>' : ""}</span>
        <span class="num${look}">${net}</span></div>`;
    });
    const text = hands.map((hand) => hand.text || "").join("\n");
    return `<div class="buttons"><button class="btn compact"${emit({cmd: "copy", text: text})}>Copy as text</button></div>
      <div class="history">${rows}</div>`;
  }

  // Every stack at once, clockwise from hero. Blank keeps the stack.
  function stacksBody(view) {
    const seats = (view.table.seats || []).filter((seat) => !seat.empty);
    const fields = list(seats, (seat, at) =>
      `<label class="field"><span class="eyebrow">${esc(seat.seat + " " + seatTitle(seat))}</span>
        <input name="${seat.seat}" value="${esc(plainAmount(view, seat.stack))}" autocomplete="off" data-fk="sweep-${seat.seat}"${at === 0 ? " data-autofocus" : ""}></label>`);
    return `<form class="stacked"${emit({op: "set_stacks", ui: {sheet: null}})} data-into="stacks" data-changed-only>
      <p class="hint">Type what you see: 12.5k, 25bb, +3k. A stack you leave as it is stays as it is (a ~ stays unsure); a minus sign empties the seat. Enter goes to the next seat and saves after the last.</p>
      <div class="cols">${fields}</div>
      <div class="buttons"><button type="submit" class="btn compact">Save ${keycap("Enter")}</button></div>
    </form>`;
  }

  /* ---------- 10. First run ---------- */

  // The likeliest values. The server may send its own under view.setup.
  const SETUP_DEFAULTS = {
    tournament: {size: "8", start_stack: "10000", level: "50/100", hero_stack: "", entrants: "", remaining: "", paid: "", buyin: ""},
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
        <p class="hint">Three players, winner takes all. Hero is seat 1.</p>`;
    } else if (mode === "aof") {
      fields = `<p class="hint">Four seats, 8 big blinds each, blinds 0.5 and 1. Everything is counted in big blinds.
        Clear a seat at the table when fewer than four play.</p>`;
    } else {
      const sizes = [2, 3, 4, 5, 6, 7, 8, 9].map((n) => ({value: String(n), label: `${n} seats`}));
      fields = `<div class="cols">
          ${setupSelect("Table", "size", d.size, sizes)}
          ${setupField("Blinds", "level", d.level, {focus: true})}
          ${setupField("Start stack", "start_stack", d.start_stack)}
          ${setupField("Your stack", "hero_stack", d.hero_stack, {placeholder: "same"})}
          ${setupField("Entrants", "entrants", d.entrants, {placeholder: "optional"})}
          ${setupField("Left", "remaining", d.remaining, {placeholder: "optional"})}
          ${setupField("Paid", "paid", d.paid, {placeholder: "optional"})}
          ${setupField("Buy-in", "buyin", d.buyin, {placeholder: "optional"})}
        </div>
        <p class="hint">Every field can be changed later. Players left and places paid switch ICM on.</p>`;
    }
    return `<form class="stacked"${emit({op: "new_session", mode: mode, ui: {sheet: null}})}>${fields}
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

  /* ---------- 11. Toast ---------- */

  function toastHtml(view, ui) {
    const toast = ui.toast !== undefined ? ui.toast : view && view.toast;
    if (!toast) return "";
    const text = typeof toast === "string" ? toast : toast.text || toast.message;
    const fix = toast.fix ? `<small>${esc(toast.fix)}</small>` : "";
    const undo = toast.undo ? `<button class="link"${emit({op: "undo", ui: {toast: null}})}>Undo</button>` : "";
    return `<div class="toast"><span class="text">${esc(text)}${fix}</span>${undo}
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
    if (ui.selected != null) return "event";
    if (ui.edit) return "edit:" + ui.edit;
    return "";
  }

  function closeTopPatch(ui) {
    ui = ui || {};
    if (ui.sheet) return {sheet: null};
    if (ui.picker) return {picker: null, pickerOff: true};
    if (ui.seatMenu != null) return {seatMenu: null, target: null};
    if (ui.menu) return {menu: null};
    if (ui.amount) return {amount: null};
    if (ui.selected != null) return {selected: null};
    if (ui.edit) return {edit: null};
    if (ui.target != null) return {target: null};
    return null;
  }

  function render(view, advice, ui) {
    ui = ui || {};
    const setup = view && view.setup;                         // the server's own defaults for the first form, if any
    if (view && view.settings && view.settings.keys) keyMap = view.settings.keys;
    const mode = (view && view.mode) || ui.setupMode || "tournament";
    if (view && (!view.table || view.first_run)) view = null; // nothing recorded yet: the first-run form
    const app = document.getElementById("app");

    // Remember where the keyboard is, and what was being typed there.
    const active = document.activeElement;
    const activeKey = focusKey(active);
    const typing = active && active.dataset && active.dataset.dirty && !active.dataset.sent
      ? {value: active.value, start: active.selectionStart, end: active.selectionEnd} : null;

    app.className = "app" + (view ? "" : " first") + (view && view.deck === "four-colour" ? " deck-four" : "");
    put("header", headerHtml(view, ui, mode));
    if (view) {
      const adviceParts = adviceHtml(view, advice, ui);
      part("advice").dataset.panel = adviceParts.panel;
      put("advice", adviceParts.html);
      part("table").classList.toggle("aof", isAof(view));
      part("table").dataset.size = view.table.size;
      put("table", tableHtml(view, ui));
      const lineChanged = put("line", lineHtml(view, ui));
      put("actions", actionsHtml(view, advice, ui));
      put("first", "");
      if (lineChanged) showLatestEvent();
    } else {
      put("advice", ""); put("table", ""); put("line", ""); put("actions", "");
      put("first", firstRunHtml(mode, setup));
    }
    ["advice", "table", "line", "actions"].forEach((name) => { part(name).hidden = !view; });
    part("first").hidden = !!view;
    const toast = toastHtml(view, ui);
    sheetToast = ui.sheet ? toast : "";
    put("overlay", overlayHtml(view, advice, ui));
    put("toast", ui.sheet ? "" : toast);
    app.inert = !!ui.sheet;                                   // a sheet is modal: the page behind it cannot be used

    moveFocus(ui, active, activeKey, typing);
  }

  // The hand line scrolls sideways: keep the newest event in sight.
  function showLatestEvent() {
    const events = part("line").querySelector(".events");
    if (events) events.scrollLeft = events.scrollWidth;
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
        const first = document.querySelector("#region-overlay [data-autofocus], #region-table .pop [data-autofocus], " +
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
          again.dataset.dirty = "1";
          try { again.setSelectionRange(typing.start, typing.end); } catch (error) { /* not a text field */ }
        }
      }
    }
  }

  function send(detail, element) {
    if (!detail || !Object.keys(detail).length) return;
    lastUsed = focusKey(element);
    document.dispatchEvent(new CustomEvent("menlo:event", {detail: detail}));
  }

  function readEmit(element) {
    try { return JSON.parse(element.dataset.emit); } catch (error) { return null; }
  }

  // The value of a field, with the name it travels under.
  function withValue(detail, field) {
    const name = field.dataset.name || field.name || "text";
    detail[name] = field.type === "checkbox" ? field.checked : field.value;
    return detail;
  }

  function isField(element) {
    return element.tagName === "INPUT" || element.tagName === "SELECT" || element.tagName === "TEXTAREA";
  }

  function onClick(event) {
    const element = event.target.closest("[data-emit]");
    if (!element || element.disabled) return;
    if (element.tagName === "FORM" || isField(element)) return;        // these send on Enter or on change
    send(readEmit(element), element);
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
      into[field.name] = field.type === "checkbox" ? field.checked : field.value;
    }
    if (changedOnly && !Object.keys(into).length) delete detail.op;    // nothing was typed: only close the sheet
    send(detail, form);
  }

  // A lone field sends on Enter, and when it is left after a change.
  function onChange(event) {
    const field = event.target;
    if (!isField(field) || !field.dataset.emit) return;
    if (field.dataset.sent === field.value) return;                    // Enter already sent this value
    field.dataset.sent = field.value;
    send(withValue(readEmit(field), field), field);
  }

  function onInput(event) {
    const field = event.target;
    if (!isField(field)) return;
    field.dataset.dirty = "1";
    delete field.dataset.sent;
  }

  function onKeyDown(event) {
    const element = event.target;
    if (event.key === "Enter" && element.tagName === "INPUT" && element.dataset.emit && element.type !== "checkbox") {
      event.preventDefault();
      element.dataset.sent = element.value;
      send(withValue(readEmit(element), element), element);
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

  let mounted = false;
  function mount() {
    if (mounted) return;
    mounted = true;
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
    format: {chips: fmtChips, short: fmtShort, stack: fmtStack, bb: fmtBb},
    SLOTS: SLOTS,
    CHOICES: CHOICES,
    // For the controller (controller.js): the same small rules the buttons use, so a key and a click do the same thing.
    pickerStep: pickerStep,
    freshPicker: freshPicker,
    isCurrent: isCurrent,
    actingSeat: actingSeat,
    seatOf: seatOf,
    spinOver: spinOver,
    seatClick: seatClick,
    only: only,
    AFTER_ACT: AFTER_ACT,
    NOTICE: NOTICE,
  };
})();
