/* ---------------------------------------------------------------------------
 * review.js - grade a deck without leaving the page.
 *
 * A session is dozens of cards, and every grade used to cost a full page load.
 * Here the grade posts in the background and the next card animates in, so a
 * deck of fifty is one page and your hands never leave the keyboard.
 *
 * Progressive: the underlying <form> still posts and still redirects, so with
 * JavaScript off the page behaves exactly as it did before.
 * ------------------------------------------------------------------------- */
(function () {
  "use strict";

  var root = document.getElementById("review");
  if (!root) return;

  var card    = root.querySelector("[data-card]");
  var form    = root.querySelector("[data-grade-form]");
  var qEl     = root.querySelector("[data-front]");
  var aEl     = root.querySelector("[data-back]");
  var reveal  = root.querySelector("[data-reveal]");
  var answer  = root.querySelector("[data-answer]");
  var counter = root.querySelector("[data-remaining]");
  var stats   = root.querySelector("[data-stats]");
  var grades  = root.querySelector("[data-grades]");
  var done    = root.querySelector("[data-done]");

  if (!card || !form) return;

  var cardId  = parseInt(root.dataset.cardId || "0", 10);
  var busy    = false;
  var shown   = false;   // is the answer revealed

  function setRevealed(on) {
    shown = on;
    answer.hidden = !on;
    reveal.hidden = on;
    // Grading before you have seen the answer is how you lie to the scheduler.
    grades.hidden = !on;
  }

  function render(next, remaining) {
    counter.textContent = remaining;
    if (!next) {
      card.hidden = true;
      grades.hidden = true;
      reveal.hidden = true;
      if (stats) stats.hidden = true;
      done.hidden = false;
      done.focus();
      return;
    }
    cardId = next.id;
    qEl.textContent = next.front;
    aEl.textContent = next.back;
    if (stats) {
      stats.textContent =
        "strength " + next.ease.toFixed(2) + " · gap " + next.interval_days + "d" +
        (next.lapses ? " · forgotten " + next.lapses + "×" : "");
    }
    setRevealed(false);
    card.classList.remove("in");
    void card.offsetWidth;            // restart the entrance
    card.classList.add("in");
    reveal.focus();
  }

  function grade(quality) {
    if (busy || !shown) return;
    busy = true;
    card.classList.add("out");

    fetch("/api/review/" + cardId, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ quality: quality }),
    })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        card.classList.remove("out");
        if (!d.ok) throw new Error(d.error || "could not grade");
        render(d.card, d.remaining);
      })
      .catch(function () {
        // Fall back to the real form post rather than silently losing a grade.
        card.classList.remove("out");
        var input = form.querySelector('input[name="quality"]');
        if (input) { input.value = quality; form.submit(); }
      })
      .finally(function () { busy = false; });
  }

  reveal.addEventListener("click", function () { setRevealed(true); });

  grades.addEventListener("click", function (e) {
    var b = e.target.closest("[data-quality]");
    if (b) grade(parseInt(b.dataset.quality, 10));
  });

  document.addEventListener("keydown", function (e) {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    var el = document.activeElement;
    if (el && /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName)) return;
    if (card.hidden) return;

    if (!shown && (e.key === " " || e.key === "Enter")) {
      e.preventDefault();
      setRevealed(true);
      return;
    }
    // 1..5 map onto the five buttons, which are SM-2 qualities 0,2,3,4,5.
    var map = { "1": 0, "2": 2, "3": 3, "4": 4, "5": 5 };
    if (shown && map.hasOwnProperty(e.key)) {
      e.preventDefault();
      grade(map[e.key]);
    }
  });

  setRevealed(false);
})();
