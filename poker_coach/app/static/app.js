/* Menlo coach: the controller.

   This file keeps what the page is showing (view, advice, ui), listens to what the user does,
   and draws again. render.js does the drawing and explains the events at its top.

   What is here now is the part that needs no server: opening and closing menus, and Esc.
   WIRING marks the places where the server calls and the keyboard map go. */
(function () {
  "use strict";

  // Development only: index.html?fixture=name draws a saved example instead (see dev-fixtures.js).
  if (new URLSearchParams(window.location.search).has("fixture")) {
    const script = document.createElement("script");
    script.src = "dev-fixtures.js";
    document.head.appendChild(script);
    return;
  }

  const state = {
    view: null,      // GET /api/view; null (or first_run: true in it) shows the first-run form
    advice: null,    // GET /api/advice?rev=N for the view on screen
    ui: {},          // what is open on this screen only
  };

  function draw() {
    window.MenloUI.render(state.view, state.advice, state.ui);
  }

  function onEvent(event) {
    const detail = event.detail;
    if (detail.ui) state.ui = Object.assign({}, state.ui, detail.ui);
    if (detail.cmd === "copy" && navigator.clipboard) navigator.clipboard.writeText(detail.text);
    // WIRING: if (detail.op) POST it to /api/intent, put the answer into state.view,
    // show an error as state.ui.toast, then ask /api/advice for the new revision.
    draw();
  }

  function onKeyDown(event) {
    if (event.key === "Escape") {
      const patch = window.MenloUI.closeTopPatch(state.ui);
      if (patch) {
        state.ui = Object.assign({}, state.ui, patch);
        draw();
      }
    }
    // WIRING: the key map of the table (seat digits, verbs, cards) goes here.
    // Skip events with event.defaultPrevented: render.js has used those (arrows, Enter in a field).
  }

  document.addEventListener("menlo:event", onEvent);
  document.addEventListener("keydown", onKeyDown);
  window.MenloUI.mount();
  draw();
  // WIRING: fetch /api/view here and draw again.
})();
