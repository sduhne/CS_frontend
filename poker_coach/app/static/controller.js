/* ==========================================================================================
   Menlo coach: the controller.

   It keeps what the page shows (view, advice, ui), talks to the server, and turns a key into the
   same event a click on the page sends. render.js draws; every poker rule is on the server.

     view     GET /api/view, and the answer to every POST /api/intent
     advice   GET /api/advice?rev=N, asked again after every new revision; an answer for an older
              revision is dropped
     ui       what is open on this screen only (the list is at the top of render.js)

   THE FOUR INPUT STATES (nothing stores them: they follow from what is on screen)
     FIELD    the cursor is in a text field: keys are text, Enter accepts, Esc cancels
     CARDS    the card picker is open: 2-9 t j q k a are ranks, s h d c suits, s and o suited and offsuit
     ACTION   a hand is being played and the cards are in: verbs, seat digits, management keys
     TABLE    between hands: seat digits, management keys

   WHICH KEY DOES WHAT is not written here: the server sends the key map of defaults.py with the
   view (view.settings.keys). COMMANDS and SEAT_COMMANDS below hold what each command does.

   Contents: 1 state, 2 the server, 3 events and drawing, 4 keys: names and states,
   5 commands of the table, 6 seat keys, 7 card keys, 8 keys in a field, 9 the keyboard, 10 start.
   ========================================================================================== */
(function () {
  "use strict";

  const UI = window.MenloUI;
  const HERO = 1;                         // hero always sits in seat 1
  const TOAST_SECONDS = 6;                // a toast goes away by itself after this long
  const ERROR_SECONDS = 12;               // ... one that says why something was refused stays longer

  /* ---------- 1. State ---------- */

  const state = {
    view: null,
    advice: null,
    ui: {},
  };
  let busy = 0;                           // intents sent and not answered yet
  const waitingKeys = [];                 // keys pressed meanwhile: they are read once the answer is in
  let lastIntent = Promise.resolve();     // intents go to the server one after the other, in the order they were made
  let keyTable = {table: {}, seat: {}, type: {}};     // key name -> command, built from view.settings.keys
  let keyTableFrom = "";                  // the key map the table was built from, as text
  let walking = false;                    // the user moves the focus with Tab or the arrows: Enter and Space press the focused button
  let swallowKeyUp = "";                  // the key whose release must not press a button
  let toastShown = "";                    // the toast on screen, to start its clock once
  let toastTimer = null;
  let setupFocused = "";                  // the mode whose first-run form already got the focus

  /* ---------- 2. The server ---------- */

  function readJson(response) { return response.json(); }

  const NO_ANSWER = {error: {message: "The program is not answering.",
                             fix: "Is it still running? Start it again (python -m poker_coach app) and reload this page."}};

  function fetchView() {
    return fetch("/api/view", {cache: "no-store"}).then(readJson).then(
      (view) => { takeView(view); draw(); askAdvice(); },
      () => { state.ui.toast = {text: NO_ANSWER.error.message, fix: NO_ANSWER.error.fix, error: true}; draw(); });
  }

  // Send one intent. `plan` says where the keyboard focus belongs afterwards (see draw);
  // `then(ok)` runs when the answer is in, before the page is drawn.
  function sendIntent(intent, plan, then) {
    busy += 1;
    const post = () => fetch("/api/intent", {
      method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(intent),
    }).then(readJson);
    lastIntent = lastIntent.then(post).then(
      (answer) => intentAnswered(intent, answer, plan, then),
      () => intentAnswered(intent, NO_ANSWER, plan, then));
  }

  function intentAnswered(intent, answer, plan, then) {
    busy -= 1;
    const error = answer.error;
    if (answer.view) takeView(answer.view);
    if (error) {
      state.ui.toast = {text: error.message, fix: error.fix, error: true};
      // A pot still needs a winner: keep the winners named so far, the bar asks for the next best hand.
      if (intent.op === "award" && error.code === "side_pot") state.ui.awardTiers = intent.ranking;
    } else {
      delete state.ui.toast;              // the toast that came with the new view shows
    }
    if (then) then(!error);
    draw(plan);
    if (answer.view) askAdvice();
    if (!error && intent.op === "new_session") noticeWasShown();
    if (!busy) readWaitingKeys();
  }

  function takeView(view) {
    const before = state.view;
    state.view = view;
    if (before && before.mode !== view.mode) {
      state.advice = null;                // another game: nothing of the old screen applies
      state.ui = {panel: state.ui.panel, toast: state.ui.toast, sheet: state.ui.sheet};
    }
    // The key map comes with every view; it is read again only when it has changed.
    const keys = view.settings && view.settings.keys;
    const text = keys ? JSON.stringify(keys) : "";
    if (text && text !== keyTableFrom) {
      keyTableFrom = text;
      keyTable = buildKeyTable(keys);
    }
  }

  // The coach's answer for the view on screen. An answer that comes back for an older view is dropped.
  // `again` counts the times a provisional answer was asked for anew.
  function askAdvice(again) {
    again = again || 0;
    const view = state.view;
    if (!view || view.first_run) return;
    const rev = view.rev;
    if (!again && state.advice && state.advice.rev === rev) return;
    fetch("/api/advice?rev=" + rev, {cache: "no-store"}).then(readJson).then((answer) => {
      if (!state.view || state.view.rev !== rev) return;          // the table has changed since: not for this screen
      if (answer.status === "stale") {
        if (!busy) fetchView();                                    // the table was changed elsewhere (a second window)
        return;
      }
      state.advice = answer;
      draw();
      // A provisional answer (charts still being worked out behind the scenes): ask again in a moment.
      if ((answer.warnings || []).some((warning) => warning.code === "charts_loading") && again < 10) {
        setTimeout(() => {
          if (state.view && state.view.rev === rev) askAdvice(again + 1);
        }, 2000);
      }
    }, () => { /* no answer from the coach: the table goes on working */ });
  }

  // The notice "for study and play money" is on the first-run form; the server remembers that it was shown.
  function noticeWasShown() {
    const settings = state.view && state.view.settings;
    if (settings && settings.notice_seen === false) sendIntent({op: "set_config", key: "notice_seen", value: true});
  }

  /* ---------- 3. Events and drawing ---------- */

  // One change, from a click (render.js sends it) or from a key (the commands below make it).
  //   detail.ui   a patch for what is open on screen     detail.op   an intent, with its arguments beside it
  //   detail.cmd  "copy"
  // `plan` is given by keys only: {} = leave the focus on nothing, {field: name} = put it into that field.
  function apply(detail, plan, then) {
    if (detail.op === "act" && skipsHero(detail.seat)) {
      state.ui = Object.assign({}, state.ui, {seatMenu: null, target: null, amount: null});
      toast("Your own action comes first.", "A player behind you cannot act before you do: F, C, X, R, A, or Space for the coach's play.");
      return;
    }
    if (detail.ui) {
      state.ui = Object.assign({}, state.ui, detail.ui);
      // The user closed the card picker and now opens something else: once that is closed, the cards are asked again.
      const opens = ["seatMenu", "menu", "sheet", "selected", "edit", "amount"].some((name) => detail.ui[name] != null);
      if (opens && !("pickerOff" in detail.ui)) state.ui.pickerOff = false;
    }
    if (detail.cmd === "copy") copyText(detail.text);
    if (detail.op) {
      const intent = Object.assign({}, detail);
      delete intent.ui;
      delete intent.cmd;
      sendIntent(intent, plan, then);
    }
    draw(plan);
  }

  // Hero's own action is always typed. The server gives every player who was passed over the passive
  // default, so an action recorded for a player behind hero, while the action is on hero, would fold
  // hero's hand without a word: that one is not sent.
  function skipsHero(seat) {
    const now = hand();
    if (!now || now.needs !== "action" || !now.target_is_hero || seat == null || seat === now.target) return false;
    const player = UI.seatOf(state.view, seat);
    if (!player || player.empty || player.folded || !player.in_hand) return false;     // the server says why these cannot act
    return (now.before_target || []).indexOf(seat) < 0;
  }

  function onPageEvent(event) {
    const detail = event.detail;
    if (detail.ui && "seatMenu" in detail.ui) state.ui.menuByKey = false;      // opened or closed by a click
    apply(detail);
  }

  function toast(text, fix) {
    state.ui.toast = {text: text, fix: fix || "", error: true};
    draw({});
  }

  function draw(plan) {
    tidyUi();
    UI.render(state.view, state.advice, state.ui);
    if (plan) settleFocus(plan);
    focusFirstRun();
    watchToast();
  }

  // Which cards the table is waiting for: hero's, or a street's.
  function wantedSlot(view) {
    const hand = view.hand;
    if (!hand) return null;
    if (hand.needs === "cards") return "hero";
    if (hand.needs !== "board") return null;
    const count = (hand.board || []).length;
    return count < 3 ? "flop" : count === 3 ? "turn" : "river";
  }

  // Before every draw: drop what no longer fits the table, and open the card picker when cards are wanted.
  function tidyUi() {
    const view = state.view, ui = state.ui;
    if (!view || view.first_run || !view.table) return;
    const hand = view.hand;
    if (!hand || hand.needs !== "action") { ui.amount = null; ui.target = null; }
    if (!hand || hand.needs !== "result") ui.awardTiers = null;
    if (!hand || (ui.selected != null && !(hand.line || []).some((event) => event.i === ui.selected))) ui.selected = null;
    if (!hand) ui.picker = null;
    if (ui.seatMenu != null && ui.seatMenu > view.table.size) ui.seatMenu = null;
    if (ui.seatMenu == null) ui.menuByKey = false;

    // CARDS: while the table waits for cards the picker is open, so the card keys are on.
    // It stays shut once the user closed it (ui.pickerOff), until other cards are wanted.
    const slot = wantedSlot(view);
    const wanted = slot ? hand.no + " " + slot : "";
    if (wanted !== ui.cardsFor) {
      ui.cardsFor = wanted;
      ui.pickerOff = false;
      ui.picker = null;
    }
    const nothingOpen = ui.seatMenu == null && !ui.menu && !ui.sheet && ui.selected == null && !ui.edit && !ui.amount;
    if (slot && !ui.picker && !ui.pickerOff && nothingOpen) ui.picker = UI.freshPicker(slot);
  }

  // After a key: the focus goes into the field the key opened, else it rests on nothing, so the
  // next key is a key of the table again. (After a click render.js looks after the focus.)
  function settleFocus(plan) {
    const active = document.activeElement;
    if (plan.field) {
      const field = document.querySelector('[data-fk="' + plan.field + '"]');
      if (field) {
        if (active !== field) {
          field.focus();
          if (field.select) field.select();     // a default is pre-selected: typing overwrites it
        }
        return;
      }
    }
    if (state.ui.sheet) return;                 // a sheet keeps its own focus
    if (active && active !== document.body) active.blur();
  }

  // The first-run form: the cursor starts in its first field (or on Start), so Enter starts the session.
  function focusFirstRun() {
    const view = state.view;
    if (!view || !view.first_run) { setupFocused = ""; return; }
    if (setupFocused === view.mode || state.ui.sheet) return;
    setupFocused = view.mode;
    const first = document.querySelector("#region-first [data-autofocus]") || document.querySelector("#region-first .btn.start");
    if (first) {
      first.focus();
      if (first.select) first.select();
    }
  }

  function watchToast() {
    const ui = state.ui;
    const shown = ui.toast !== undefined ? ui.toast : state.view && state.view.toast;
    const text = shown ? JSON.stringify(shown) + (state.view ? state.view.rev : "") : "";
    if (text === toastShown) return;
    toastShown = text;
    clearTimeout(toastTimer);
    if (!shown) return;
    toastTimer = setTimeout(() => {
      state.ui.toast = null;
      draw();
    }, 1000 * (shown.error ? ERROR_SECONDS : TOAST_SECONDS));
  }

  function copyText(text) {
    const copied = () => { state.ui.toast = {text: "Copied."}; draw(); };
    const oldWay = () => {
      const box = document.createElement("textarea");
      box.value = text;
      document.body.appendChild(box);
      box.select();
      try { document.execCommand("copy"); copied(); } catch (error) { toast("The browser did not allow the copy."); }
      box.remove();
    };
    if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(text).then(copied, oldWay);
    else oldWay();
  }

  // A value in the strip that is being typed closes when the cursor leaves it.
  function onFocusOut(event) {
    const fk = (event.target.dataset && event.target.dataset.fk) || "";
    if (fk.indexOf("edit-") !== 0) return;
    setTimeout(() => {
      const field = document.querySelector('[data-fk="' + fk + '"]');
      if (state.ui.edit && field && document.activeElement !== field) apply({ui: {edit: null}});
    }, 0);
  }

  /* ---------- 4. Keys: names and states ---------- */

  // The name of a key as defaults.py writes it: "n", "?", "Shift+S", "Ctrl+z", "Space", "Alt+1".
  function keyName(event) {
    let key = event.key;
    if (key === " ") key = "Space";
    if (event.altKey && /^Digit[0-9]$/.test(event.code || "")) key = event.code.slice(5);    // Alt changes the character on some keyboards
    const letter = key.length === 1 && key.toLowerCase() !== key.toUpperCase();
    if (letter) key = event.shiftKey ? key.toUpperCase() : key.toLowerCase();                // Caps Lock makes no difference
    let name = "";
    if (event.ctrlKey || event.metaKey) name += "Ctrl+";
    if (event.altKey) name += "Alt+";
    if (event.shiftKey && (letter || key.length > 1)) name += "Shift+";                      // "?" and "{" already say that Shift is held
    return name + key;
  }

  function buildKeyTable(keys) {
    const table = {};
    Object.keys(keys).forEach((group) => {
      table[group] = {};
      keys[group].forEach((row) => row.keys.forEach((key) => { table[group][key] = row.do; }));
    });
    return {table: table.table || {}, seat: table.seat || {}, type: table.type || {}};
  }

  function isField(element) {
    return !!element && (element.tagName === "INPUT" || element.tagName === "SELECT" || element.tagName === "TEXTAREA");
  }
  function isButton(element) {
    return !!element && (element.tagName === "BUTTON" || element.tagName === "A");
  }

  // Could this key mean something to the table? (Tab, F5, Ctrl+R and the like never do.)
  function isTableKey(name) {
    return name.length === 1 || !!keyTable.table[name] ||
           ["Space", "Enter", "Backspace", "Delete", "Escape", "ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].indexOf(name) >= 0;
  }

  function hand() { return state.view && state.view.hand; }
  function lineItem(index) {
    const now = hand();
    return (now && (now.line || []).find((event) => event.i === index)) || null;
  }
  // Players still in the pot who were not named a winner yet.
  function liveSeats() {
    const ranked = [].concat.apply([], state.ui.awardTiers || []);
    return state.view.table.seats.filter((seat) => !seat.empty && seat.in_hand && !seat.folded && ranked.indexOf(seat.seat) < 0);
  }

  /* ---------- 5. Commands of the table (TABLE and ACTION) ---------- */

  // Record an action. Without a seat it is for the player the action is on (hero whenever he still owes a decision).
  function recordAct(kind, seat) {
    const now = hand();
    if (!now || now.needs !== "action") {
      // Cards are wanted first: say so, and bring the card picker back if it was closed.
      if (now && (now.needs === "cards" || now.needs === "board")) state.ui.pickerOff = false;
      if (now && now.needs === "cards") toast("Your cards first.", "Type them: A K S, or A H K D.");
      else if (now && now.needs === "board") toast("The cards of this street first.", "Type them: K S 7 D 2 C. Enter skips the board.");
      return;
    }
    if (seat == null) seat = now.target;
    if (kind === "bet" || kind === "raise") { askAmount(seat); return; }
    apply({op: "act", seat: seat, kind: kind, ui: UI.AFTER_ACT}, {});
  }

  // A bet or a raise needs an amount.
  function askAmount(seat) {
    const view = state.view, now = view.hand;
    if (view.mode === "aof") { toast("All-In or Fold has two moves.", "A is all-in, F is fold."); return; }
    const player = UI.seatOf(view, seat);
    if (seat === now.target && player && player.is_hero) {
      // Hero's own bet is always typed: the field opens at the coach's size (or the usual one) and Enter accepts it.
      const legal = now.legal || {};
      const kind = legal.bet ? "bet" : legal.raise ? "raise" : null;
      if (!kind) { toast("No raise is possible here.", "Call, fold or move all-in."); return; }
      const follow = UI.isCurrent(view, state.advice) ? state.advice.headline.follow : null;
      const coachSize = follow && (follow.kind === "bet" || follow.kind === "raise") && follow.to != null ? String(follow.to) : null;
      apply({ui: {amount: {kind: kind, seat: seat, text: coachSize}, seatMenu: null, selected: null}}, {field: "amount"});
      return;
    }
    // An opponent's bet is recorded at once at the likeliest size, so the coach can already answer;
    // the amount is selected and open: type the real one and Enter, or just go on.
    apply({op: "act", seat: seat, kind: "raise", ui: UI.AFTER_ACT}, {field: "event-amount"}, (ok) => {
      const acts = ok && hand() ? hand().line.filter((event) => event.kind === "act" && event.seat === seat) : [];
      const last = acts[acts.length - 1];
      // (a raise that was not possible is recorded as a call, and an all-in has no amount to type)
      if (last && (last.verb === "raise" || last.verb === "bet")) state.ui.selected = last.i;
    });
  }

  // Who won. A side pot the winner is not in asks again (see intentAnswered).
  function award(seats) {
    const now = hand();
    if (!now || now.needs !== "result") return;
    apply({op: "award", ranking: (state.ui.awardTiers || []).concat([seats]), ui: {seatMenu: null}}, {});
  }

  // Enter: the rest of the players take the passive default; while a street's cards are wanted, the street is skipped.
  function restDefault() {
    const now = hand();
    if (!now || (now.needs !== "action" && now.needs !== "board")) return;
    if (now.target_is_hero) {
      // It would be hero's fold (or check) too: his own action is always typed.
      if (now.needs === "board") toast("The action is on you on this street.", "Type its cards first: K S 7 D 2 C.");
      else toast("The action is on you.", "Space does what the coach says; or F, C, X, R, A.");
      return;
    }
    apply({op: "close_round", ui: UI.AFTER_ACT}, {});
  }

  function walkLine(step) {
    const now = hand();
    const line = (now && now.line) || [];
    if (!line.length) return;
    let at = line.findIndex((event) => event.i === state.ui.selected);
    if (at < 0) at = step < 0 ? line.length : -1;       // nothing selected: Left starts at the last step, Right at the first
    at = Math.max(0, at + step);
    if (at >= line.length) { apply({ui: {selected: null, picker: null}}, {}); return; }      // past the end: nothing is selected
    const item = line[at];
    const patch = UI.only({selected: item.i});
    // Cards are changed by typing them again: the picker opens on that slot.
    if (item.kind !== "act" && now.needs !== "next") patch.picker = UI.freshPicker(item.kind === "board" ? item.street : "hero");
    apply({ui: patch}, {});
  }

  const COMMANDS = {
    deal() {
      // Spin & Gold: once a game is over the same key starts the next one (300 chips: the x2 and x3 games).
      if (UI.spinOver(state.view)) apply({op: "new_game", start_stack: 300, ui: UI.only({})}, {});
      else apply({op: "deal", ui: UI.only({})}, {});
    },
    new_game_500() {
      if (state.view.mode === "spin") apply({op: "new_game", start_stack: 500, ui: UI.only({})}, {});
    },
    follow() {
      const view = state.view, now = view.hand;
      if (!now || now.needs !== "action" || !now.target_is_hero) return;       // no decision of hero's to follow
      if (!UI.isCurrent(view, state.advice)) {
        toast("The coach has not answered this spot yet.", "Wait for the answer; or act with F, C, X, R, A.");
        return;
      }
      const follow = state.advice.headline.follow;
      if (!follow) { toast("The coach names no action here.", "Act with F, C, X, R, A."); return; }
      apply({op: "act", seat: now.target, via: "follow", kind: follow.kind, to: follow.to, ui: UI.AFTER_ACT}, {});
    },
    fold() { recordAct("fold"); },
    call() { recordAct("call"); },
    check() { recordAct("check"); },
    bet() { recordAct("bet"); },
    raise() { recordAct("raise"); },
    allin() { recordAct("allin"); },
    accept: restDefault,
    won() {
      if (liveSeats().some((seat) => seat.is_hero)) award([HERO]);
    },
    lost() {
      const now = hand();
      if (!now || now.needs !== "result") return;
      const others = liveSeats().filter((seat) => !seat.is_hero);
      if (others.length === 1) award([others[0].seat]);
      else toast("More than one opponent is in the pot.", "Press the winner's seat number, then W.");
    },
    split() {
      award(liveSeats().map((seat) => seat.seat));
    },
    undo() { apply({op: "undo", ui: {toast: null}}, {}); },
    redo() { apply({op: "redo", ui: {toast: null}}, {}); },
    discard() { apply({op: "discard_hand", ui: UI.only({})}, {}); },
    line_back() { walkLine(-1); },
    line_on() { walkLine(1); },
    edit() {
      const now = hand();
      if (!now) return;
      const bets = (now.line || []).filter((event) => event.kind === "act" && !event.auto &&
                                                      ["bet", "raise", "call", "allin"].indexOf(event.verb) >= 0);
      const selected = lineItem(state.ui.selected);
      const item = bets.indexOf(selected) >= 0 ? selected : bets.filter((event) => event.verb !== "call").pop();
      if (!item) { toast("There is no bet to change in this hand."); return; }
      apply({ui: UI.only({selected: item.i})}, {field: "event-amount"});
    },
    delete() {
      const item = lineItem(state.ui.selected);
      if (!item) { toast("Select an action first.", "Left and Right walk the hand line."); return; }
      if (item.kind !== "act") { toast("Cards are not deleted.", "Type the right ones over them."); return; }
      apply({op: "remove_event", index: item.i, ui: {selected: null}}, {});
    },
    button_back() { apply({op: "button_step", step: -1}, {}); },
    button_on() { apply({op: "button_step", step: 1}, {}); },
    seat_fewer() { apply({op: "set_size", delta: -1}, {}); },
    seat_more() { apply({op: "set_size", delta: 1}, {}); },
    blinds_up() { apply({op: "level_up"}, {}); },
    blinds_down() { apply({op: "level_down"}, {}); },
    blinds() {
      if (state.view.mode === "aof") { toast("All-In or Fold has fixed blinds."); return; }
      apply({ui: UI.only({edit: "level"})}, {field: "edit-level"});
    },
    ante() { apply({op: "set_ante_kind"}, {}); },
    left_minus() { apply({op: "remaining", step: -1}, {}); },
    left_plus() { apply({op: "remaining", step: 1}, {}); },
    left_minus_ten() { apply({op: "remaining", step: -10}, {}); },
    left_plus_ten() { apply({op: "remaining", step: 10}, {}); },
    stacks() { apply({ui: UI.only({sheet: "stacks"})}, {}); },
    my_stack() { apply({ui: UI.only({seatMenu: HERO, menuByKey: true})}, {field: "seat-stack"}); },
    my_seat_out() { apply({op: "set_status", seat: HERO}, {}); },
    tournament() {
      // Players left is the number that changes all the time: it is typed in place. The rest is in the menu.
      if (state.view.mode === "tournament") apply({ui: UI.only({edit: "remaining"})}, {field: "edit-remaining"});
      else apply({ui: UI.only({sheet: "settings"})}, {});
    },
    style() {
      // No value: the server moves to the next choice.
      apply({op: "set_config", key: state.view.mode === "tournament" ? "style" : "opponents"}, {});
    },
    unit() {
      if (state.view.mode !== "aof") apply({op: "set_config", key: "unit"}, {});       // All-In or Fold is always in big blinds
    },
    history() { apply({ui: UI.only({sheet: "history"})}, {}); },
    keys() { apply({ui: UI.only({sheet: state.ui.sheet === "keys" ? null : "keys"})}, {}); },
    mode_tournament() { apply({op: "set_mode", mode: "tournament", ui: {setupMode: "tournament"}}, {}); },
    mode_spin() { apply({op: "set_mode", mode: "spin", ui: {setupMode: "spin"}}, {}); },
    mode_aof() { apply({op: "set_mode", mode: "aof", ui: {setupMode: "aof"}}, {}); },
    cancel: closeTop,
  };

  // Esc: close the topmost open thing. Returns false when nothing was open.
  function closeTop() {
    const patch = UI.closeTopPatch(state.ui);
    if (!patch) return false;
    apply({ui: patch}, {});
    return true;
  }

  /* ---------- 6. Seat keys ---------- */

  // A seat digit: the seat's menu opens and the next key is for that player.
  function seatDigit(seat) {
    const view = state.view, now = view.hand;
    const player = UI.seatOf(view, seat);
    if (!player) { toast("There is no seat " + seat + " at this table.", "Seats run from 1 to " + view.table.size + "."); return; }

    // "The action was on the wrong seat": with an action selected on the hand line, the digit moves it.
    const selected = lineItem(state.ui.selected);
    if (selected && selected.kind === "act") {
      apply({op: "edit_event", index: selected.i, seat: seat, ui: {selected: null}}, {});
      return;
    }
    // All-In or Fold has one move: during a hand the digit alone is that player's all-in, and again takes it back.
    if (view.mode === "aof" && now && now.needs === "action" && !player.empty) {
      const shoves = now.line.filter((event) => event.kind === "act" && event.seat === seat && event.allin && !event.auto);
      if (shoves.length) apply({op: "remove_event", index: shoves[shoves.length - 1].i}, {});
      else apply({op: "act", seat: seat, kind: "allin", ui: UI.AFTER_ACT}, {});
      return;
    }
    const patch = Object.assign({}, UI.seatClick(view, player).ui, {menuByKey: true});
    apply({ui: patch}, player.empty ? {field: "add-stack"} : {});
  }

  const SEAT_COMMANDS = {
    // f c x b r a after a digit: that player's action. The verb is the one the key has at the table.
    act(seat, key) {
      const verb = keyTable.table[key];
      if (["fold", "call", "check", "bet", "raise", "allin"].indexOf(verb) >= 0) recordAct(verb, seat);
    },
    won(seat) { award([seat]); },
    stack() { settleFocus({field: "seat-stack"}); },
    name() { settleFocus({field: "seat-name"}); },
    type() { settleFocus({field: "seat-type"}); },      // then one of the type keys (see fieldKey)
    note() { settleFocus({field: "seat-note"}); },
    sit_out(seat) { apply({op: "set_status", seat: seat}, {}); },
    button(seat) { apply({op: "set_button", seat: seat, ui: {seatMenu: null, target: null}}, {}); },
    bust(seat) { apply({op: "bust", seat: seat, ui: {seatMenu: null, target: null}}, {}); },
    clear(seat) { apply({op: "clear_seat", seat: seat, ui: {seatMenu: null, target: null}}, {}); },
  };

  function seatKey(key) {
    const command = keyTable.seat[key.name];
    if (!command || !SEAT_COMMANDS[command]) return false;
    SEAT_COMMANDS[command](state.ui.seatMenu, key.name);
    return true;
  }

  /* ---------- 7. Card keys (CARDS) ---------- */

  const RANK_KEYS = {a: "A", k: "K", q: "Q", j: "J", t: "T", 0: "T", 9: "9", 8: "8", 7: "7", 6: "6", 5: "5", 4: "4", 3: "3", 2: "2"};
  const SUIT_KEYS = "shdc";

  // Returns true when the key was a card key (also one that makes no sense right now: it is then ignored,
  // never read as a key of the table, so "o" can never sit hero out while cards are typed).
  function cardKey(key) {
    const view = state.view, picker = state.ui.picker;
    const name = key.name;
    let step;
    if (name === "Backspace") step = {back: true};
    else if (RANK_KEYS[name]) step = {rank: RANK_KEYS[name]};
    else if (name === "s") step = picker.rank2 ? {mark: "s"} : {suit: "s"};     // after two ranks S is "suited", else spades
    else if (name === "o") step = {mark: "o"};
    else if (SUIT_KEYS.indexOf(name) >= 0) step = {suit: name};
    else if (name === "1") return true;                 // no card starts with 1; the ten is T (or 0)
    else if (name === "Enter") { leaveCards(); return true; }
    else return false;

    const detail = UI.pickerStep(view, picker, step);
    if (detail) apply(detail, {});
    else if (step.back) return false;                   // nothing typed yet: Backspace is undo, as at the table
    else if (step.suit && picker.rank) toast("The " + picker.rank + step.suit + " is already on the table.", "Each card exists once.");
    return true;
  }

  // Enter while the picker is open: skip the board when a street's cards are wanted and none is typed; else just leave.
  function leaveCards() {
    const picker = state.ui.picker, now = hand();
    const empty = !picker.rank && !(picker.cards || []).length;
    if (picker.slot !== "hero" && empty && now.needs === "board") restDefault();
    else apply({ui: {picker: null, pickerOff: true}}, {});
  }

  /* ---------- 8. Keys in a field (FIELD) ---------- */

  const AMOUNT_KEYS = /^[0-9.,kmbx%+\- ]$/i;    // what an amount is typed with: 1,300  12.5k  25bb  3x  66%

  // Returns true when the key was used here; false lets the browser type it into the field.
  function fieldKey(key, field, live) {
    const fk = field.dataset.fk || "";
    if (key.name === "Escape") { closeTop(); return true; }

    // The type keys, after a seat digit and T: N nit, T tight, G tag ...
    if (fk === "seat-type" && keyTable.type[key.name]) {
      apply({op: "set_type", seat: state.ui.seatMenu, type: keyTable.type[key.name], ui: {seatMenu: null, target: null}}, {});
      return true;
    }
    // An opponent's bet that was recorded at the likeliest size (see askAmount): while its amount is untouched,
    // Enter accepts it, and a key that is no part of an amount accepts it and is then a key of the table.
    if (fk === "event-amount" && !field.dataset.dirty) {
      if (key.name === "Enter") { apply({ui: {selected: null}}, {}); return true; }
      const typed = key.name.length === 1 ? key.name : "";
      if (key.name === "Space" || (typed && !AMOUNT_KEYS.test(typed) && keyTable.table[key.name])) {
        apply({ui: {selected: null}}, {});
        return tableKey(key);
      }
    }
    // The amount of a bet takes digits and the letters amounts are written with; another letter is not typed into it.
    if ((fk === "amount" || fk === "event-amount") && key.name.length === 1 && !AMOUNT_KEYS.test(key.name)) return true;
    // Up and Down in the amount of a bet walk through the sizes offered as buttons.
    if (fk === "amount" && (key.name === "ArrowUp" || key.name === "ArrowDown")) {
      stepPreset(field, key.name === "ArrowUp" ? 1 : -1);
      return true;
    }
    // The stack sweep: Enter goes on to the next seat; on the last one it saves.
    if (fk.indexOf("sweep-") === 0 && key.name === "Enter") {
      const fields = Array.prototype.slice.call(document.querySelectorAll('[data-fk^="sweep-"]'));
      const next = fields[fields.indexOf(field) + 1];
      if (next) { next.focus(); next.select(); return true; }
    }
    if (!live) { typeInto(field, key); return true; }
    // A seat's menu that was opened by its digit closes when a value is accepted (4 S 12.5k Enter).
    if (key.name === "Enter" && state.ui.menuByKey && fk.indexOf("seat-") === 0) {
      setTimeout(() => apply({ui: {seatMenu: null, target: null}}, {}), 0);
    }
    return false;
  }

  function stepPreset(field, step) {
    const now = hand();
    const sizes = ((now && now.presets) || []).map((preset) => preset.to);
    if (!sizes.length) return;
    const typed = Number(String(field.value).replace(/,/g, ""));
    const at = isNaN(typed) ? (step > 0 ? -Infinity : Infinity) : typed;
    const next = step > 0 ? sizes.find((size) => size > at) : sizes.slice().reverse().find((size) => size < at);
    if (next == null) return;
    field.value = String(next);
    field.dataset.dirty = "1";
    field.select();
  }

  // A key that waited for the server's answer and now belongs to a field: put it in as the browser would have.
  function typeInto(field, key) {
    if (key.name === "Enter") {
      if (field.form && !field.dataset.emit) field.form.requestSubmit();
      else field.dispatchEvent(new KeyboardEvent("keydown", {key: "Enter", bubbles: true, cancelable: true}));
      return;
    }
    if (!field.setRangeText) return;
    let start = field.selectionStart, end = field.selectionEnd;
    if (key.name === "Backspace") {
      if (start === end && start > 0) start -= 1;
      field.setRangeText("", start, end, "end");
    } else if (key.text) {
      field.setRangeText(key.text, start, end, "end");
    } else {
      return;
    }
    field.dispatchEvent(new Event("input", {bubbles: true}));
  }

  /* ---------- 9. The keyboard ---------- */

  // A key at the table (the focus is in no field). Returns true when the key was used.
  function tableKey(key) {
    const digit = /^[1-9]$/.test(key.name);
    walking = false;
    if (state.ui.picker && cardKey(key)) return true;                   // CARDS: digits are ranks
    if (state.ui.seatMenu != null) {                                    // after a seat digit
      if (seatKey(key)) return true;
      // Any other key drops the seat and is read as usual (another digit goes to that seat, Esc closes the menu).
      if (!digit && key.name !== "Escape") state.ui = Object.assign({}, state.ui, {seatMenu: null, target: null});
    }
    if (digit) { seatDigit(Number(key.name)); return true; }
    const command = keyTable.table[key.name];
    if (!command || !COMMANDS[command]) return false;
    const used = COMMANDS[command]() !== false;
    restFocus();
    return used;
  }

  // A key of the table was used while a button had the focus (it was clicked before): the focus
  // leaves the button, so that Enter and Space stay keys of the table.
  function restFocus() {
    const active = document.activeElement;
    if (!state.ui.sheet && isButton(active)) active.blur();
  }

  // One key, live from the keyboard or one that waited for the server. Returns true when it was used.
  function handleKey(key, live) {
    const view = state.view, ui = state.ui;
    if (!view) return false;
    const active = document.activeElement;

    // The keys that change the game (Alt+1, Alt+2, Alt+3) work everywhere, also while a field has the cursor.
    const command = keyTable.table[key.name] || "";
    if (command.indexOf("mode_") === 0) { COMMANDS[command](); return true; }
    // The first-run form and the sheets are forms: the browser's own keys, plus Esc and "?".
    if (view.first_run || ui.sheet) {
      if (key.name === "Escape") return closeTop();
      if (isField(active)) return fieldKey(key, active, live);
      if (command === "keys") { COMMANDS.keys(); return true; }
      return false;
    }
    if (isField(active)) return fieldKey(key, active, live);                                   // FIELD
    // After Tab the white ring is on a button: Enter and Space press that button.
    if (walking && isButton(active) && (key.name === "Enter" || key.name === "Space")) return false;
    return tableKey(key);
  }

  function readWaitingKeys() {
    while (waitingKeys.length && !busy) handleKey(waitingKeys.shift(), false);
  }

  function onKeyDown(event) {
    if (event.isComposing || ["Shift", "Control", "Alt", "Meta"].indexOf(event.key) >= 0) return;
    const key = {name: keyName(event), text: event.key.length === 1 ? event.key : ""};
    const active = document.activeElement;
    if (event.defaultPrevented) {
      // render.js used it: an arrow moved the focus inside a group, or Enter sent a field.
      if (key.name.indexOf("Arrow") === 0) walking = true;
      if (key.name === "Enter" && isField(active)) fieldKey(key, active, true);
      return;
    }
    if (key.name === "Tab" || key.name === "Shift+Tab") { walking = true; return; }
    if (event.repeat && !isField(active)) {             // a held key is one key
      if (isTableKey(key.name)) event.preventDefault();
      return;
    }
    // An intent is on its way: what this key means may depend on the answer, so it waits.
    // (Typing into a field goes on meanwhile.)
    if (busy && isTableKey(key.name) && !(isField(active) && !waitingKeys.length)) {
      waitingKeys.push(key);
      event.preventDefault();
      return;
    }
    if (handleKey(key, true)) {
      event.preventDefault();
      if (key.name === "Space" || key.name === "Enter") swallowKeyUp = event.key;
    }
  }

  // A button pressed with Space is clicked when the key comes up: not when the key was used by the table.
  function onKeyUp(event) {
    if (swallowKeyUp && event.key === swallowKeyUp) event.preventDefault();
    swallowKeyUp = "";
  }

  /* ---------- 10. Start ---------- */

  function start() {
    UI.mount();                                         // first: render.js sees a key before this file does
    document.addEventListener("menlo:event", onPageEvent);
    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("keyup", onKeyUp);
    document.addEventListener("mousedown", () => { walking = false; });
    document.addEventListener("focusout", onFocusOut);
    return fetchView().then(() => {
      // A session made before this page first opened: say once what the program is for.
      const view = state.view;
      if (view && !view.first_run && view.settings && view.settings.notice_seen === false) {
        state.ui.toast = {text: UI.NOTICE};
        draw();
        noticeWasShown();
      }
    });
  }

  window.MenloController = {
    start: start,
    state: state,                                       // for a look from the browser's console, and for the browser tests
    // Nothing is on its way: no intent, and the coach has answered for the view on screen.
    settled: function () {
      const view = state.view;
      if (!view || busy || waitingKeys.length) return false;
      return !!view.first_run || !!(state.advice && state.advice.rev === view.rev);
    },
  };
})();
