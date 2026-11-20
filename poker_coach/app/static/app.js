/* Menlo coach: the page starts here.

   render.js draws the page from data, controller.js talks to the server and reads the keys.
   This file only decides which of the two ways the page runs. */
(function () {
  "use strict";

  // Development only: index.html?fixture=name draws a saved example with no server (see dev-fixtures.js).
  if (new URLSearchParams(window.location.search).has("fixture")) {
    const script = document.createElement("script");
    script.src = "dev-fixtures.js";
    document.head.appendChild(script);
    return;
  }

  window.MenloController.start();
})();
