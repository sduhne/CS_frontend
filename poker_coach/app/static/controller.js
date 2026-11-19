/* ==========================================================================================
   Menlo coach: the controller.

   It keeps what the page shows (view, advice, ui), talks to the server, and turns a key into the
   same event a click on the page sends. render.js draws; every poker rule is on the server.

     view     GET /api/view, and the answer to every POST /api/intent
     advice   GET /api/advice?rev=N, asked again after every new revision; an answer for an older
              revision is dropped
     ui       what is open on this screen only (the list is at the top of render.js)

   THE FOUR INPUT STATES (nothing stores them: they follow from what is on screen)
     FIELD    the cursor is in a text field: keys are text, Enter accepts, Esc cancels (the field's
              first value comes back and nothing is sent). A value the server refuses stays in its
              open field, selected, with the reason under it (ui.fieldError).
     CARDS    the card picker is open: 2-9 t j q k a are ranks, s h d c suits, s and o suited and offsuit
     ACTION   a hand is being played and the cards are in: verbs, seat digits, management keys
     TABLE    between hands: seat digits, management keys

   WHOSE ACTION A PLAIN KEY RECORDS is what the first row of the action bar says (UI.actingSeat):
     hero, whenever he still owes a decision: the players in front of him then take the passive default;
     the next player otherwise; and, once the user has recorded an opponent with a plain key in this
     betting round (ui.turn), the next player in turn until the turn reaches hero.
     A seat digit first aims one action at that seat, whatever the bar says.

   NOTHING CHANGES WITHOUT A WORD: where the model has no toast of its own for a change (a stack, a
   player sitting out, a one-key setting) sayWhatChanged makes one, with Undo.

   THE TABLE MAY CHANGE ELSEWHERE (another window): every intent carries the revision of the view on
   screen, the server refuses one for an older table (code "stale") and the page then shows the table
   as it is; the view is read again when the tab gets the focus.

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
  let fieldWaits = 0;                     // values sent from a field and not answered yet: keys wait, the answer says where they go
  let menuDrawn = null;                   // the seat whose menu is drawn, and whether the screen has shown it yet
  let menuSeen = false;

  /* ---------- 2. The server ---------- */

  function readJson(response) { return response.json(); }

  const NO_ANSWER = {error: {message: "The program is not answering.",
                             fix: "Is it still running? Start it again (double-click Start Poker Coach) and reload this page."}};
  const DROPPED = {dropped: true};        // an intent that was not sent: the table had changed under the keys before it
  let epoch = 0;                          // goes up each time the table turns out to have changed elsewhere
  let traffic = 0;                        // goes up with every intent sent and every answer taken

  // Read the table from the program. `ifNew`: only take it when it is another revision than the one on
  // screen (the tab got the focus back: another window may have changed the table meanwhile).
  function fetchView(ifNew) {
    const asked = traffic;
    return fetch("/api/view", {cache: "no-store"}).then((response) => response.json().then((data) => ({ok: response.ok, data: data}))).then(
      (answer) => {
        // An intent went out or came back while this look was on its way: its answer is the newer table.
        if (ifNew && (busy || traffic !== asked)) return;
        const view = answer.data;
        if (!answer.ok || !view || view.error || view.rev == null) {
          // The program answered, but with no table: say what it said. The first-run form is for a
          // session that does not exist yet, never for one that cannot be shown.
          const error = (view && view.error) || {};
          showViewError({message: error.message || "The program could not show the table.",
                         fix: error.fix || "Undo takes back the last change. If that does not help, start a new tournament: the old file stays in its folder."});
          return;
        }
        if (ifNew && state.view && state.view.rev === view.rev && !!state.view.first_run === !!view.first_run && !state.ui.viewError) return;
        state.ui.viewError = null;
        takeView(view);
        draw();
        askAdvice();
      },
      () => {
        if (ifNew && state.view) return;                    // the table on screen stays; the next key says if the program is gone
        showViewError(Object.assign({down: true}, NO_ANSWER.error));
      });
  }
  function showViewError(error) {
    state.view = null;
    state.advice = null;
    state.ui = {viewError: error, sheet: state.ui.sheet === "new" ? "new" : null};
    draw();
  }

  // Send one intent. `plan` says where the keyboard focus belongs afterwards (see draw);
  // `then(ok, error)` runs when the answer is in, before the page is drawn.
  // Every intent carries the revision of the view on screen ("rev"); one that was typed ahead is sent
  // once the answer before it is in, so it carries the revision of that answer. When the program says
  // the table had changed meanwhile (code "stale"), nothing was done: the page shows the table as it
  // is now, and what was typed ahead for the old one is dropped.
  function sendIntent(intent, plan, then) {
    busy += 1;
    const made = epoch;
    const post = () => {
      if (made !== epoch) return DROPPED;
      traffic += 1;
      const rev = state.view && state.view.rev != null ? {rev: state.view.rev} : {};
      return fetch("/api/intent", {
        method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(Object.assign({}, intent, rev)),
      }).then(readJson);
    };
    lastIntent = lastIntent.then(post).then(
      (answer) => intentAnswered(intent, answer, plan, then),
      () => intentAnswered(intent, NO_ANSWER, plan, then));
  }

  function intentAnswered(intent, answer, plan, then) {
    busy -= 1;
    traffic += 1;
    if (answer === DROPPED) {             // typed for a table that had changed: not sent
      if (then) then(false, {message: "", dropped: true});
      draw(plan);
      return;
    }
    const error = answer.error;
    const before = state.view;
    if (answer.view && answer.view.rev != null) {
      state.ui.viewError = null;
      takeView(answer.view);
    }
    if (error && error.code === "stale") {
      // Another window (or an old tab) changed the table: nothing was done. Show it as it is.
      epoch += 1;
      waitingKeys.length = 0;
      state.advice = null;
      state.ui = Object.assign({}, state.ui, UI.only({}), {target: null, turn: null, awardTiers: null,
        toast: {text: "The table had changed: look again and repeat.", fix: "It was changed in another window. Nothing was done here.", error: true}});
      if (then) then(false, error);
      draw({});
      if (!answer.view) fetchView(); else askAdvice();
      return;
    }
    if (error) {
      state.ui.toast = {text: error.message, fix: error.fix, error: true};
      // A pot still needs a winner: keep the winners named so far, the bar asks for the next best hand.
      if (intent.op === "award" && error.code === "side_pot") { state.ui.awardTiers = intent.ranking; state.ui.split = null; }
      // A smaller table with a player on the last seat: the toast offers to clear the seat and remove it.
      const offer = error && intent.op === "set_size" ? clearAndShrink(intent) : null;
      if (offer) state.ui.toast = {text: error.message, error: true, action: offer};       // (the button says what to do instead)
    } else {
      delete state.ui.toast;              // the toast that came with the new view shows
      state.ui.fieldError = null;
      sayWhatChanged(intent, before, state.view);
    }
    const after = then ? then(!error, error) : null;       // (a field's answer may ask for the cursor: see fieldAnswered)
    draw(plan);
    if (after && after.field) focusField(after.field, true);
    if (answer.view) askAdvice();
    if (!error && intent.op === "new_session") noticeWasShown();
    if (!busy) readWaitingKeys();
  }

  /* A change the model made without a word of its own gets one here, with Undo: a stack, a player
     sitting out, a setting changed by one key. Nothing changes silently. */
  function sayWhatChanged(intent, before, view) {
    if (!before || !view || !view.table || !before.table || before.mode !== view.mode) return;
    const words = [];
    const fmt = UI.format;
    const stackText = (seat) => view.unit === "bb" && view.mode !== "aof" ? fmt.bb(seat.stack_bb, true) + "bb"
      : view.mode === "aof" ? fmt.bb(seat.stack, true) + "bb" : fmt.chips(seat.stack);
    const who = (seat) => seat.is_hero ? "Your stack" : "Seat " + seat.seat;
    if (intent.op === "set_stack" || intent.op === "set_stacks") {
      const changed = [];
      view.table.seats.forEach((seat) => {
        const old = UI.seatOf(before, seat.seat);
        if (!old || seat.empty || old.empty) return;
        if (old.stack !== seat.stack) changed.push(who(seat) + ": " + stackText(old) + " to " + stackText(seat));
        else if (old.stale && !seat.stale) changed.push(who(seat) + ": " + stackText(seat) + ", confirmed");
      });
      if (changed.length > 3) words.push(changed.length + " stacks changed");
      else if (changed.length) words.push(changed.join(" \u00b7 "));
    }
    if (intent.op === "set_status") {
      const seat = UI.seatOf(view, intent.seat), old = UI.seatOf(before, intent.seat);
      if (seat && old && seat.status !== old.status && (seat.status === "away" || old.status === "away")) {
        const name = seat.is_hero ? "You" : "Seat " + seat.seat + (seat.name ? " (" + seat.name + ")" : "");
        if (seat.status === "away") words.push(seat.is_hero ? "You are sitting out: O sits you back in" : name + " sits out");
        else words.push(seat.is_hero ? "You are back in" : name + " is back in");
      }
    }
    if (intent.op === "set_config" || intent.op === "set_ante_kind" || intent.op === "set_tournament") {
      const label = (list, value) => ((list || []).find((choice) => choice.value === value) || {label: String(value)}).label;
      const C = UI.CHOICES, a = before.strip || {}, b = view.strip || {};
      if (a.style !== b.style) words.push("Style: " + label(C.style, b.style));
      if (a.plan !== b.plan) words.push("Moves: " + (UI.MOVES_WORDS[b.plan] || label(C.plan, b.plan)));
      if (a.opponents !== b.opponents) words.push("Opponents: " + label(C.opponents[view.mode], b.opponents));
      if (before.unit !== view.unit) words.push("Numbers in " + (view.unit === "bb" ? "big blinds" : "chips"));
      if ((before.deck || "") !== (view.deck || "")) words.push("Deck: " + label(C.deck, view.deck));
      const kind = (strip) => (strip.level || {}).ante_kind;
      if (kind(a) !== kind(b)) words.push("Ante: " + label(C.ante_kind, kind(b)).toLowerCase());
      if (!!a.reentry_open !== !!b.reentry_open) words.push(b.reentry_open ? "Re-entry is open" : "Re-entry is closed");
      if (!!a.bounty !== !!b.bounty) words.push(b.bounty ? "Bounty tournament" : "No bounty");
    }
    // The blinds and the players left change every answer, and one key changes them.
    if (["level_up", "level_down", "set_level", "set_ladder"].indexOf(intent.op) >= 0) {
      // (new blinds typed during a hand wait for the next one: that level is the one to name)
      const level = (strip) => { const now = (strip || {}).level || {}; return now.pending || now; };
      const a = level(before.strip), b = level(view.strip);
      if (a.sb !== b.sb || a.bb !== b.bb || (a.ante || 0) !== (b.ante || 0)) {
        const waits = view.strip.level && view.strip.level.pending ? " from the next hand" : "";
        words.push("Blinds: " + fmt.short(b.sb) + " / " + fmt.short(b.bb) + (b.ante ? ", ante " + fmt.short(b.ante) : ", no ante") + waits);
      }
    }
    if (intent.op === "remaining" && before.strip && view.strip && before.strip.remaining !== view.strip.remaining && view.strip.remaining != null) {
      words.push("Players left: " + fmt.chips(view.strip.remaining));
    }
    if (!words.length) return;
    const own = words.join(" \u00b7 ");
    const said = view.toast && view.toast.text ? String(view.toast.text) : "";
    // The model's own sentence stays; ours is put in front unless it says the same.
    const text = said && said.indexOf(own) < 0 ? own + " \u00b7 " + said : said || own;
    state.ui.toast = {text: text, undo: !!(view.can && view.can.undo)};
  }

  // "- Seat" was refused because the seats above the new size are taken: what the toast offers instead.
  function clearAndShrink(intent) {
    const view = state.view;
    if (!view || !view.table) return null;
    const size = view.table.size;
    const want = intent.size != null ? Number(intent.size) : size + Number(intent.delta || 0);
    if (!(want < size) || intent.clear) return null;
    const taken = view.table.seats.filter((seat) => seat.seat > want && !seat.empty).map((seat) => seat.seat);
    if (!taken.length) return null;
    const label = taken.length === 1 ? "Clear seat " + taken[0] + " and remove it" : "Clear seats " + taken.join(", ") + " and remove them";
    return {label: label, send: {op: "set_size", size: want, clear: true}};
  }

  function fieldOf(fk) { return document.querySelector('[data-fk="' + fk + '"]'); }

  // Put the cursor into a field; `select`: with its text selected, so typing replaces it.
  function focusField(fk, select) {
    const field = fieldOf(fk);
    if (!field) return false;
    if (document.activeElement !== field) field.focus();
    if (select && field.select) field.select();
    return true;
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
  //   detail.ui     a patch for what is open on screen     detail.op   an intent, with its arguments beside it
  //   detail.cmd    "copy", "reload"
  //   detail.from   {fk, value}: the field the value was typed into. Its ui patch then waits for the answer.
  //   detail.after  a ui patch for once the server has done the intent
  //   detail.plain  (act) true: not aimed at a seat, so it starts or continues recording in turn
  // `plan` is given by keys only: {} = leave the focus on nothing, {field: name} = put it into that field.
  function apply(detail, plan, then) {
    if (detail.op === "act" && skipsHero(detail.seat)) {
      state.ui = Object.assign({}, state.ui, {seatMenu: null, target: null, amount: null});
      toast("Your own action comes first.", "A player behind you cannot act before you do: " + ownKeys() + ", or Space for the coach's play.");
      return;
    }
    // An action recorded for an opponent without aiming at his seat (a plain key, or a button of the bar
    // while it names him): the user is recording the players in turn. The plain keys then keep going in
    // turn, also once a raise makes hero owe a decision, until the turn reaches hero (see UI.actingSeat).
    if (detail.op === "act" && "plain" in detail) {
      const player = UI.seatOf(state.view, detail.seat);
      if (detail.plain && player && !player.is_hero) state.ui.turn = UI.roundKey(state.view);
      detail = Object.assign({}, detail);
      delete detail.plain;
    }
    // A value typed into a field (detail.from): what it closes is closed once the server has taken
    // the value. A refused one stays in its open field, with the reason under it (see fieldAnswered).
    const from = detail.op ? detail.from : null;
    if (detail.ui && !from) patchUi(detail.ui);
    if (detail.cmd === "copy") copyText(detail.text);
    if (detail.cmd === "reload") fetchView();
    if (detail.op) {
      const intent = Object.assign({}, detail);
      delete intent.ui;
      delete intent.cmd;
      delete intent.from;
      delete intent.after;
      // detail.after: what opens once the server has done it (New table, then the sheet for the stacks).
      if (detail.after) {
        const inner = then;
        then = (ok, error) => { if (ok) patchUi(detail.after); return inner ? inner(ok, error) : null; };
      }
      if (from) {
        fieldWaits += 1;
        sendIntent(intent, plan, (ok, error) => {
          fieldWaits -= 1;
          const after = fieldAnswered(detail, ok, error);
          if (then) then(ok, error);
          return after;
        });
      } else {
        sendIntent(intent, plan, then);
      }
    }
    draw(plan);
  }

  function patchUi(patch) {
    state.ui = Object.assign({}, state.ui, patch);
    // The user closed the card picker and now opens something else: once that is closed, the cards are asked again.
    const opens = ["seatMenu", "menu", "sheet", "selected", "edit", "amount"].some((name) => patch[name] != null);
    if (opens && !("pickerOff" in patch)) state.ui.pickerOff = false;
  }

  // The server has answered a value that came from a field.
  function fieldAnswered(detail, ok, error) {
    const from = detail.from;
    if (ok) {
      if (detail.ui) patchUi(detail.ui);
      // A seat's menu that was opened by its digit closes when a value is accepted (4 S 12.5k Enter).
      if (state.ui.menuByKey && String(from.fk).indexOf("seat-") === 0) patchUi({seatMenu: null, target: null});
      return null;
    }
    // Refused. While the field is still open it keeps what was typed, selected, and says why under it;
    // the next keys go into it. (A field that was left meanwhile, or a whole form: the toast says why.)
    if (!from.fk || !fieldOf(from.fk)) return null;
    state.ui.fieldError = {fk: from.fk, text: error.message, fix: error.fix || "", value: from.value};
    if (!state.ui.sheet) state.ui.toast = null;       // a sheet says it at its foot as well
    return {field: from.fk};
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

  // The keys of hero's own action, for a sentence: All-In or Fold has two.
  function ownKeys() { return state.view && state.view.mode === "aof" ? "A or F" : "F, C, X, R, A"; }

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
    watchSeatMenu();
  }

  // A seat's menu counts as open once the screen has shown it: a frame was painted with it.
  function watchSeatMenu() {
    const seat = state.ui.seatMenu != null && document.querySelector("#region-table .pop") ? state.ui.seatMenu : null;
    if (seat === menuDrawn) return;
    menuDrawn = seat;
    menuSeen = false;
    if (seat != null) requestAnimationFrame(() => requestAnimationFrame(() => { if (menuDrawn === seat) menuSeen = true; }));
  }
  // Run `job` once the seat menu that is drawn now has been on the screen. Keys typed meanwhile wait.
  function onceMenuSeen(job) {
    if (menuSeen || menuDrawn == null) { job(); return; }
    const seat = menuDrawn;
    let ran = false;
    busy += 1;
    const run = () => {
      if (ran) return;
      ran = true;
      busy -= 1;
      if (menuDrawn === seat) { menuSeen = true; job(); }
      if (!busy) readWaitingKeys();
    };
    requestAnimationFrame(() => requestAnimationFrame(run));
    setTimeout(run, 150);                 // a window that is not being painted (it is hidden) must not hold the key for ever
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
    if (!hand || hand.needs !== "result") { ui.awardTiers = null; ui.split = null; }
    if (!hand || (ui.selected != null && !(hand.line || []).some((event) => event.i === ui.selected))) ui.selected = null;
    if (ui.editing != null && ui.editing !== ui.selected) ui.editing = null;
    if (ui.sheet !== "history") ui.handOpen = null;
    // Recording in turn lasts for one betting round, and ends when the turn reaches hero.
    if (ui.turn && (!hand || hand.needs !== "action" || ui.turn !== UI.roundKey(view) ||
                    (hand.target_is_hero && !(hand.before_target || []).length))) ui.turn = null;
    if (!hand) ui.picker = null;
    if (ui.seatMenu != null && ui.seatMenu > view.table.size) ui.seatMenu = null;
    if (ui.seatMenu == null) ui.menuByKey = false;
    if (ui.fieldError && !fieldIsOpen(ui, ui.fieldError.fk)) ui.fieldError = null;

    // CARDS: while the table waits for cards the picker is open, so the card keys are on.
    // It stays shut once the user closed it (ui.pickerOff), until other cards are wanted.
    const slot = wantedSlot(view);
    const wanted = slot ? hand.no + " " + slot : "";
    if (wanted !== ui.cardsFor) {
      ui.cardsFor = wanted;
      ui.pickerOff = false;
      ui.picker = null;
    }
    const nothingOpen = ui.seatMenu == null && !ui.menu && !ui.sheet && ui.selected == null && !ui.edit && !ui.amount && !ui.split;
    if (slot && !ui.picker && !ui.pickerOff && nothingOpen) ui.picker = UI.freshPicker(slot);
  }

  // Is the field with this data-fk on screen, going by what is open?
  function fieldIsOpen(ui, fk) {
    if (fk.indexOf("seat-") === 0 || fk.indexOf("add-") === 0) return ui.seatMenu != null;
    if (fk.indexOf("edit-") === 0) return ui.edit === fk.slice(5);
    if (fk === "amount") return !!ui.amount;
    if (fk === "event-amount") return ui.editing != null;
    return !!ui.sheet;
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

  // Record an action. Without a seat it is for the player the bar names: hero whenever he still owes a
  // decision, else the next player; and the next player in turn while the user records in turn.
  function recordAct(kind, seat) {
    const now = hand();
    const aimed = seat != null;
    // A player named by his seat can also be given an action once the betting is over (the hand waits
    // for a street's cards or for the result): a caller who was forgotten. The model reopens the round,
    // or says in a sentence why it cannot.
    const late = aimed && now && (now.needs === "board" || now.needs === "result" || (now.needs === "cards" && now.want_suits));
    if (late) {
      apply({op: "act", seat: seat, kind: kind, ui: UI.AFTER_ACT}, {});
      return;
    }
    if (!now || now.needs !== "action") {
      // Cards are wanted first: say so, and bring the card picker back if it was closed.
      if (now && (now.needs === "cards" || now.needs === "board")) state.ui.pickerOff = false;
      if (now && now.needs === "cards") toast("Your cards first.", "Type them: A K S, or A H K D.");
      else if (now && now.needs === "board") toast("The cards of this street first.", "Type them: K S 7 D 2 C. Enter skips the board.");
      else if (now && now.needs === "result") toast("The betting is over.", "W or L says who won. A forgotten caller: his seat number, then C.");
      return;
    }
    const plain = !aimed && state.ui.target == null;
    if (!aimed) seat = UI.actingSeat(state.view, state.ui);
    if (kind === "bet" || kind === "raise") { askAmount(seat, plain); return; }
    apply({op: "act", seat: seat, kind: kind, plain: plain, ui: UI.AFTER_ACT}, {});
  }

  // A bet or a raise needs an amount.
  function askAmount(seat, plain) {
    const view = state.view, now = view.hand;
    if (view.mode === "aof") { toast("All-In or Fold has two moves.", "A is all-in, F is fold."); return; }
    const player = UI.seatOf(view, seat);
    if (seat === now.target && player && player.is_hero) {
      // Hero's own bet is always typed: the field opens at the coach's size (or the usual one) and Enter accepts it.
      const legal = now.legal || {};
      const kind = legal.bet ? "bet" : legal.raise ? "raise" : null;
      if (!kind) { toast("No raise is possible here.", "Call, fold or move all-in."); return; }
      const follow = UI.isCurrent(view, state.advice) ? state.advice.headline.follow : null;
      const coachSize = follow && (follow.kind === "bet" || follow.kind === "raise") && follow.to != null ? follow.to : null;
      apply({ui: {amount: {kind: kind, seat: seat, to: coachSize}, seatMenu: null, selected: null}}, {field: "amount"});
      return;
    }
    // An opponent's bet is recorded at once at the likeliest size, so the coach can already answer, and
    // the next keys are keys of the table again (7 R 8 C records the raise and the call).
    // E, or a click on the chip, opens the amount.
    apply({op: "act", seat: seat, kind: "raise", plain: !!plain, ui: UI.AFTER_ACT}, {});
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
      // While the players in front of hero are recorded in turn: the rest of them fold, and the keys are hero's.
      if (now.needs === "action" && state.ui.target == null && UI.actingSeat(state.view, state.ui) !== now.target) {
        apply({ui: {turn: null}}, {});
        return;
      }
      // It would be hero's fold (or check) too: his own action is always typed.
      if (now.needs === "board") toast("The action is on you on this street.", "Type its cards first: K S 7 D 2 C.");
      else toast("The action is on you.", "Space does what the coach says; or " + ownKeys() + ".");
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
    // Cards are changed by typing them again: the picker opens on that slot (hero's cards: to be replaced, on purpose).
    if (item.kind !== "act" && now.needs !== "next") patch.picker = UI.freshPicker(item.kind === "board" ? item.street : "hero", true);
    apply({ui: patch}, {});
  }

  const COMMANDS = {
    deal() {
      // Spin & Gold: once a game is over the same key starts the next one (300 chips: the x2 and x3 games).
      if (UI.spinOver(state.view)) apply({op: "new_game", start_stack: 300, ui: UI.only({})}, {});
      else if (UI.heroOutOfChips(state.view)) {
        // No chips: a hand dealt now would be dealt without hero.
        toast("You have no chips.", "S: type a new stack to re-enter. Or start a new " +
              (state.view.mode === "tournament" ? "tournament" : "game") + " from the settings.");
      }
      else apply({op: "deal", ui: UI.only({})}, {});
    },
    new_game_500() {
      if (state.view.mode === "spin") apply({op: "new_game", start_stack: 500, ui: UI.only({})}, {});
    },
    follow() {
      const view = state.view, now = view.hand;
      if (!now || now.needs !== "action" || !now.target_is_hero) return;       // no decision of hero's to follow
      const acting = UI.seatOf(view, UI.actingSeat(view, state.ui));
      if (acting && !acting.is_hero) {
        toast((acting.pos || "Seat " + acting.seat) + " acts before you.", "Record that player first; or Enter: the players before you fold.");
        return;
      }
      if (!UI.isCurrent(view, state.advice)) {
        toast("The coach has not answered this spot yet.", "Wait for the answer; or act with " + ownKeys() + ".");
        return;
      }
      const follow = state.advice.headline.follow;
      if (!follow) { toast("The coach names no action here.", "Act with " + ownKeys() + "."); return; }
      apply({op: "act", seat: now.target, via: "follow", kind: follow.kind, to: follow.to, ui: UI.AFTER_ACT}, {});
    },
    fold() { recordAct("fold"); },
    call() { recordAct("call"); },
    check() { recordAct("check"); },
    bet() { recordAct("bet"); },
    raise() { recordAct("raise"); },
    allin() { recordAct("allin"); },
    accept() {
      // While a split is ticked together, Enter is its button.
      const ticked = state.ui.split;
      if (ticked) {
        if (ticked.length >= 2) apply({op: "award", ranking: (state.ui.awardTiers || []).concat([ticked]), ui: {split: null, seatMenu: null}}, {});
        else toast("Tick two or more players.", "Press their seat numbers; Esc cancels the split.");
        return;
      }
      restDefault();
    },
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
      const now = hand();
      if (!now || now.needs !== "result") return;
      const live = liveSeats();
      // Two players: they split. More: who shares the pot is ticked (seat numbers, or clicks), then Enter.
      if (live.length > 2) apply({ui: UI.only({split: []})}, {});
      else award(live.map((seat) => seat.seat));
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
      apply({ui: UI.only({selected: item.i, editing: item.i})}, {field: "event-amount"});
    },
    delete() {
      const item = lineItem(state.ui.selected);
      if (!item) { toast("Select an action first.", "Left and Right walk the hand line."); return; }
      if (item.kind !== "act") { toast("Cards are not deleted.", "Type the right ones over them."); return; }
      apply({op: "remove_event", index: item.i, ui: {selected: null, editing: null}}, {});
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
      // Players left is the number that changes all the time: it is typed in place. The rest is in the settings.
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

    // A split is being ticked together: the digit ticks that player, or unticks him.
    if (state.ui.split) {
      if (!liveSeats().some((live) => live.seat === seat)) { toast("Seat " + seat + " is not in this pot.", "Tick players who reached the showdown."); return; }
      const ticked = state.ui.split;
      apply({ui: {split: ticked.indexOf(seat) >= 0 ? ticked.filter((n) => n !== seat) : ticked.concat([seat])}}, {});
      return;
    }
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
    // Sit out, bust and clear change who is at the table. They act through the seat's menu, once it is
    // on the screen, and the toast names the seat and offers Undo: keys that were meant as cards
    // (Q 4 O without N first) cannot remove a player without a word.
    sit_out(seat) { onceMenuSeen(() => apply({op: "set_status", seat: seat, ui: {seatMenu: null, target: null}}, {})); },
    button(seat) { apply({op: "set_button", seat: seat, ui: {seatMenu: null, target: null}}, {}); },
    bust(seat) { onceMenuSeen(() => apply({op: "bust", seat: seat, ui: {seatMenu: null, target: null}}, {})); },
    clear(seat) { onceMenuSeen(() => apply({op: "clear_seat", seat: seat, ui: {seatMenu: null, target: null}}, {})); },
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
    else if (step.suit && UI.wantSuits(view, picker)) {
      toast("No " + view.hand.want_suits.hand + " like that is left.", "Pick one of the holdings shown: the other cards are on the table.");
    }
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
    // Esc cancels: the field's first value comes back and nothing is sent, whatever closes with it.
    if (key.name === "Escape") { UI.cancelField(field); closeTop(); return true; }

    // An empty seat's menu (the cursor is in the stack of the player to add): D puts the dealer button there.
    if (fk === "add-stack" && keyTable.seat[key.name] === "button" && state.ui.seatMenu != null) {
      apply({op: "set_button", seat: state.ui.seatMenu, ui: {seatMenu: null, target: null}}, {});
      return true;
    }
    // The type keys, after a seat digit and T: N nit, T tight, G tag ...
    if (fk === "seat-type" && keyTable.type[key.name]) {
      apply({op: "set_type", seat: state.ui.seatMenu, type: keyTable.type[key.name], ui: {seatMenu: null, target: null}}, {});
      return true;
    }
    // An opponent's bet that was recorded at the likeliest size (see askAmount): while its amount is untouched,
    // Enter accepts it, and a key that is no part of an amount accepts it and is then a key of the table.
    if (fk === "event-amount" && !field.dataset.dirty) {
      if (key.name === "Enter") { apply({ui: {selected: null, editing: null}}, {}); return true; }
      const typed = key.name.length === 1 ? key.name : "";
      if (key.name === "Space" || (typed && !AMOUNT_KEYS.test(typed) && keyTable.table[key.name])) {
        apply({ui: {selected: null, editing: null}}, {});
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
    return false;
  }

  function stepPreset(field, step) {
    const now = hand();
    const sizes = ((now && now.presets) || []).map((preset) => preset.to);
    if (!sizes.length) return;
    // (The field is in big blinds while the numbers are shown so: its text is compared as chips.)
    const inBb = field.dataset.unit === "bb";
    const bb = inBb ? state.view.strip.level.bb : 1;
    let typed = Number(String(field.value).replace(/,/g, "")) * bb;
    if (inBb && field.dataset.exact != null && field.value === field.dataset.exactText) typed = Number(field.dataset.exact);
    const at = isNaN(typed) ? (step > 0 ? -Infinity : Infinity) : typed;
    const next = step > 0 ? sizes.find((size) => size > at + 1e-9) : sizes.slice().reverse().find((size) => size < at - 1e-9);
    if (next == null) return;
    field.value = UI.plainAmount(state.view, next);
    if (inBb) { field.dataset.exact = String(next); field.dataset.exactText = field.value; }
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
    if (state.ui.menu === "newtable" && key.name === "Enter") {         // the New table menu: Enter sits down
      const go = fieldOf("nt-start");
      if (go) go.click();
      return true;
    }
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
    if (!view) {                                            // no table to show (see showViewError): Esc closes a sheet
      if (key.name === "Escape" && ui.sheet) { apply({ui: {sheet: null}}); return true; }
      return false;
    }
    const active = document.activeElement;

    // The keys that change the game (Alt+1, Alt+2, Alt+3) work everywhere, also while a field has the cursor.
    const command = keyTable.table[key.name] || "";
    if (command.indexOf("mode_") === 0) {
      if (isField(active)) UI.cancelField(active);          // a half-typed value is not saved on the way out
      COMMANDS[command]();
      return true;
    }
    // The first-run form and the sheets are forms: the browser's own keys, plus Esc and "?".
    if (view.first_run || ui.sheet) {
      if (key.name === "Escape") {
        if (isField(active)) UI.cancelField(active);        // Esc cancels what is being typed
        return closeTop() || isField(active);
      }
      // Undo and redo with Ctrl work on the first-run form as well (an undone start can be made again),
      // unless a field holds text of its own to undo.
      if (view.first_run && (command === "undo" || command === "redo") && key.name.indexOf("Ctrl+") === 0 &&
          !(isField(active) && active.dataset.dirty)) { COMMANDS[command](); return true; }
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
    // (... unless the field's own value is on its way: the answer says whether the field stays open.)
    if (busy && isTableKey(key.name) && !(isField(active) && !waitingKeys.length && !fieldWaits)) {
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
    // The tab was away: another window may have changed the table. Look again when it is back.
    const lookAgain = () => { if (!busy && !document.hidden) fetchView(true); };
    window.addEventListener("focus", lookAgain);
    document.addEventListener("visibilitychange", lookAgain);
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
      if (busy || waitingKeys.length) return false;
      if (!view) return !!state.ui.viewError;             // (the screen that says the table cannot be shown)
      return !!view.first_run || !!(state.advice && state.advice.rev === view.rev);
    },
  };
})();
