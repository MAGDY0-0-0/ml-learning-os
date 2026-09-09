/* ---------------------------------------------------------------------------
 * app.js — shell behaviour.
 *
 *  - Ctrl/Cmd-K command palette over every unit, module and project
 *  - toasts, so saving a note no longer costs a full page reload
 *  - progressive form enhancement: forms marked data-quiet post in the
 *    background and confirm inline, instead of round-tripping the whole page
 *
 * No dependencies. Everything here degrades to the plain form it enhances.
 * ------------------------------------------------------------------------- */
(function () {
  "use strict";

  /* ------------------------------------------------------------- toasts -- */
  var host = document.getElementById("toasts");

  function toast(msg, kind) {
    if (!host) return;
    var el = document.createElement("div");
    el.className = "toast";
    el.innerHTML =
      '<svg class="i" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
      'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><use href="#ic-' +
      (kind === "bad" ? "alert" : "check-circle") + '"/></svg><span></span>';
    el.lastChild.textContent = msg;
    if (kind === "bad") el.querySelector(".i").style.color = "var(--bad)";
    host.appendChild(el);
    setTimeout(function () {
      el.classList.add("out");
      el.addEventListener("animationend", function () { el.remove(); });
    }, 2600);
  }
  window.toast = toast;

  /* --------------------------------------------------- quiet form posts -- */
  // A form with data-quiet keeps you where you are: it posts in the
  // background, shows a toast, and never scrolls you back to the top.
  document.addEventListener("submit", function (e) {
    var form = e.target.closest("form[data-quiet]");
    if (!form) return;
    e.preventDefault();
    var btn = form.querySelector('button[type="submit"], button:not([type])');
    var was = btn ? btn.textContent : "";
    if (btn) { btn.disabled = true; btn.textContent = "Saving…"; }

    fetch(form.action, { method: "POST", body: new FormData(form) })
      .then(function (r) {
        toast(form.dataset.quiet || (r.ok ? "Saved" : "Could not save"), r.ok ? "ok" : "bad");
      })
      .catch(function () { toast("Could not save — is the app still running?", "bad"); })
      .finally(function () { if (btn) { btn.disabled = false; btn.textContent = was; } });
  });

  /* ----------------------------------------------------------- palette -- */
  var dlg = null, input = null, list = null, items = [], shown = [], sel = 0;

  function buildPalette() {
    dlg = document.createElement("dialog");
    dlg.className = "palette";
    dlg.innerHTML =
      '<div class="box">' +
        '<input type="search" placeholder="Jump to a unit, module or project…" ' +
               'aria-label="Search" autocomplete="off" spellcheck="false">' +
        '<ul role="listbox"></ul>' +
      "</div>";
    document.body.appendChild(dlg);
    input = dlg.querySelector("input");
    list = dlg.querySelector("ul");

    input.addEventListener("input", function () { render(input.value); });
    dlg.addEventListener("click", function (e) {
      if (e.target === dlg) dlg.close();       // click outside the box
    });
    dlg.addEventListener("keydown", function (e) {
      if (e.key === "ArrowDown") { e.preventDefault(); move(1); }
      else if (e.key === "ArrowUp") { e.preventDefault(); move(-1); }
      else if (e.key === "Enter") {
        e.preventDefault();
        var a = list.querySelector('li[aria-selected="true"] a');
        if (a) window.location.href = a.href;
      }
    });
  }

  function move(d) {
    if (!shown.length) return;
    sel = (sel + d + shown.length) % shown.length;
    paint();
  }

  function paint() {
    var lis = list.querySelectorAll("li");
    for (var i = 0; i < lis.length; i++) {
      lis[i].setAttribute("aria-selected", i === sel ? "true" : "false");
    }
    if (lis[sel] && lis[sel].scrollIntoView) lis[sel].scrollIntoView({ block: "nearest" });
  }

  function render(q) {
    q = (q || "").trim().toLowerCase();
    shown = q
      ? items.filter(function (it) { return (it.k + " " + it.t).toLowerCase().indexOf(q) > -1; }).slice(0, 40)
      : items.slice(0, 40);
    sel = 0;

    if (!shown.length) {
      list.innerHTML = '<li class="none">Nothing matches “' + escapeHtml(q) + "”.</li>";
      return;
    }
    list.innerHTML = shown.map(function (it) {
      return '<li role="option"><a href="' + it.u + '">' +
             '<span class="k">' + escapeHtml(it.k) + "</span>" +
             '<span class="grow">' + escapeHtml(it.t) + "</span></a></li>";
    }).join("");
    paint();
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  function openPalette() {
    if (!dlg) buildPalette();
    var go = function () {
      if (!dlg.open) dlg.showModal();
      input.value = "";
      render("");
      input.focus();
    };
    if (items.length) return go();
    fetch("/api/search-index")
      .then(function (r) { return r.json(); })
      .then(function (d) { items = d.items || []; go(); })
      .catch(function () { items = []; go(); });
  }

  document.addEventListener("click", function (e) {
    if (e.target.closest("[data-palette-open]")) openPalette();
  });

  document.addEventListener("keydown", function (e) {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      openPalette();
      return;
    }
    // "/" focuses search, the way every tool with a search box behaves
    if (e.key === "/" && !/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName)) {
      e.preventDefault();
      openPalette();
    }
  });
})();
