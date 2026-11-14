/* ---------------------------------------------------------------------------
 * docview.js - the PDF quick-view drawer.
 *
 * A library search already knows the page a phrase is on. Before this, it told
 * you the number and left you to go and find it. Now the hit is a control:
 * clicking it opens the PDF at that page in a drawer over the current screen,
 * so you never lose the unit - or the video's position - to look something up.
 *
 * PDF.js is served from app/static/vendor/ and loaded on the first open only.
 * ------------------------------------------------------------------------- */
(function () {
  "use strict";

  // The 3.x UMD build, because it defines window.pdfjsLib. 4.x and later are
  // ES modules that export instead, which a plain <script> cannot reach.
  // Served from this machine: the drawer works offline, and the worker is
  // same-origin, so pdf.js never has to fall back to running on the page.
  var PDFJS_VERSION = "3.11.174";
  var LIB = "/static/vendor/pdfjs-" + PDFJS_VERSION;

  var dlg = null, body = null, titleEl = null, pageEl = null;
  var doc = null, page = 1, scale = 1.3;
  // The render in flight, and a counter that every new request bumps. There
  // used to be a `rendering` flag here instead: a second Next press while a
  // page was drawing was dropped, but `page` had already moved, so the label,
  // the canvas and the counter disagreed -- and a render that never settled
  // left the flag set and the drawer dead until a reload.
  var task = null, seq = 0;
  var current = { id: null, title: "", pages: 0 };

  // ---- chrome ------------------------------------------------------------
  function build() {
    dlg = document.createElement("dialog");
    dlg.className = "drawer";
    dlg.innerHTML =
      '<form method="dialog"><button class="scrim" aria-label="Close the document"></button></form>' +
      '<div class="sheet">' +
        '<div class="sheet-bar">' +
          '<span class="nm"></span>' +
          '<span class="pageno"></span>' +
          '<button type="button" data-act="prev">← Prev</button>' +
          '<button type="button" data-act="next">Next →</button>' +
          '<button type="button" data-act="out">−</button>' +
          '<button type="button" data-act="in">+</button>' +
          '<button type="button" data-act="cite">Cite into notes</button>' +
          '<button type="button" data-act="close">Close (Esc)</button>' +
        '</div>' +
        '<div class="sheet-body"><p class="loading">Opening…</p></div>' +
      '</div>';
    document.body.appendChild(dlg);

    body    = dlg.querySelector(".sheet-body");
    titleEl = dlg.querySelector(".nm");
    pageEl  = dlg.querySelector(".pageno");

    dlg.addEventListener("click", function (e) {
      var act = e.target.closest("[data-act]");
      if (!act) return;
      var a = act.dataset.act;
      if (a === "prev")  go(page - 1);
      if (a === "next")  go(page + 1);
      if (a === "in")  { scale = Math.min(3, scale + 0.2); render(); }
      if (a === "out") { scale = Math.max(0.6, scale - 0.2); render(); }
      if (a === "close") dlg.close();
      if (a === "cite") cite(act);
    });

    dlg.addEventListener("keydown", function (e) {
      if (e.key === "ArrowRight" || e.key === "PageDown") { e.preventDefault(); go(page + 1); }
      if (e.key === "ArrowLeft"  || e.key === "PageUp")   { e.preventDefault(); go(page - 1); }
    });
  }

  // ---- pdf.js ------------------------------------------------------------
  function loadPdfJs() {
    if (window.pdfjsLib) return Promise.resolve(window.pdfjsLib);
    return new Promise(function (resolve, reject) {
      var s = document.createElement("script");
      s.src = LIB + "/pdf.min.js";
      s.onload = function () {
        if (!window.pdfjsLib) return reject(new Error("pdf.js did not load"));
        window.pdfjsLib.GlobalWorkerOptions.workerSrc = LIB + "/pdf.worker.min.js";
        resolve(window.pdfjsLib);
      };
      s.onerror = function () { reject(new Error("viewer missing")); };
      document.head.appendChild(s);
    });
  }

  function fail(msg) {
    body.innerHTML = '<p class="failed"></p>';
    body.querySelector(".failed").textContent = msg;
  }

  function open(docId, startPage, title) {
    if (!dlg) build();
    current.id = docId;
    current.title = title || "Document";
    page = Math.max(1, parseInt(startPage, 10) || 1);
    titleEl.textContent = current.title;
    pageEl.textContent = "page " + page;
    body.innerHTML = '<p class="loading">Opening ' + escapeHtml(current.title) + "…</p>";
    if (!dlg.open) dlg.showModal();

    // A different document replaces this one: stop drawing it and free it.
    var opening = ++seq;
    if (task) { task.cancel(); task = null; }
    if (doc) { doc.destroy(); doc = null; }

    loadPdfJs()
      .then(function (lib) {
        return lib.getDocument("/library/doc/" + docId).promise;
      })
      .then(function (d) {
        if (opening !== seq) { d.destroy(); return; }  // another open() won
        doc = d;
        current.pages = d.numPages;
        page = Math.min(page, d.numPages);
        render();
      })
      .catch(function (err) {
        fail(
          err && err.message === "viewer missing"
            ? "The PDF viewer's files are missing from app\\static\\vendor. The file is still on disk in library\\ — open it there."
            : "That file could not be opened. It may have been moved or renamed since the last reindex."
        );
      });
  }

  function go(n) {
    if (!doc) return;
    var next = Math.min(Math.max(1, n), doc.numPages);
    if (next === page) return;
    page = next;
    render();
  }

  // Draw `page` at `scale`. A newer request cancels this one; a canvas is
  // only swapped in if the page it shows is still the one asked for, so
  // pressing Next five times quickly lands exactly five pages on.
  function render() {
    if (!doc) return;
    var mine = ++seq, want = page, dpr = window.devicePixelRatio || 1;
    pageEl.textContent = "page " + want + " / " + doc.numPages;
    if (task) { task.cancel(); task = null; }

    doc.getPage(want).then(function (pg) {
      if (mine !== seq) return;
      var vp = pg.getViewport({ scale: scale * dpr });
      var canvas = document.createElement("canvas");
      canvas.width = vp.width;
      canvas.height = vp.height;
      canvas.style.width = (vp.width / dpr) + "px";
      var t = task = pg.render({ canvasContext: canvas.getContext("2d"), viewport: vp });
      return t.promise.then(function () {
        if (task === t) task = null;
        if (mine !== seq) return;
        body.replaceChildren(canvas);
        body.scrollTop = 0;
      });
    }).catch(function (err) {
      if (err && err.name === "RenderingCancelledException") return;
      if (mine !== seq) return;
      fail("That page could not be rendered.");
    });
  }

  // ---- citing ------------------------------------------------------------
  // Writes "Title, p.N" plus your selection into the current unit's notes.
  function cite(btn) {
    var unit = document.body.dataset.unitSlug;
    if (!unit) {
      flash(btn, "Open a unit first");
      return;
    }
    var quote = String(window.getSelection() || "").trim();
    var line = "> " + (quote || "(no text selected)") +
               "\n> — " + current.title + ", p." + page + "\n";
    fetch("/unit/" + unit + "/notes/append", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: line }),
    })
      .then(function (r) { flash(btn, r.ok ? "Added to notes" : "Could not save"); })
      .catch(function () { flash(btn, "Could not save"); });
  }

  function flash(btn, msg) {
    var was = btn.textContent;
    btn.textContent = msg;
    setTimeout(function () { btn.textContent = was; }, 1800);
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  // ---- wiring ------------------------------------------------------------
  document.addEventListener("click", function (e) {
    var hit = e.target.closest("[data-doc-id]");
    if (!hit) return;
    e.preventDefault();
    open(hit.dataset.docId, hit.dataset.docPage, hit.dataset.docTitle);
  });
})();
