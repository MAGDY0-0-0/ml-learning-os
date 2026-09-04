/* ---------------------------------------------------------------------------
 * player.js - the in-app YouTube player.
 *
 * You still watch on YouTube's servers; this just removes the friction around
 * it. It remembers where you stopped, logs the minutes you actually watched
 * so you never type "25" into a box again, ticks the resource off at 90%, and
 * gives you a real playlist rail for the multi-video units.
 *
 * Everything degrades: with no network the poster stays, the links still work,
 * and the forms underneath are untouched.
 * ------------------------------------------------------------------------- */
(function () {
  "use strict";

  var root = document.getElementById("player");
  if (!root) return;

  var RID       = root.dataset.resourceId;
  var UNIT      = root.dataset.unitSlug;
  var VIDEO_ID  = root.dataset.videoId || "";
  var LIST_ID   = root.dataset.listId || "";
  var START_AT  = parseInt(root.dataset.startAt || "0", 10) || 0;
  var ALREADY   = root.dataset.done === "1";

  var poster   = root.querySelector(".poster");
  var fill     = root.querySelector(".track > i");
  var clock    = root.querySelector("[data-clock]");
  var status   = root.querySelector("[data-status]");
  var openLink = document.getElementById("open-at");
  var railBox  = document.getElementById("rail");

  var yt = null;              // the YT.Player instance
  var lastSavedAt = 0;        // seconds of playback position last persisted
  var watchedSecs = 0;        // seconds actually watched this visit
  var creditedMin = 0;        // whole minutes already sent to the server
  var marked = ALREADY;
  var ticker = null;

  function fmt(s) {
    s = Math.max(0, Math.floor(s || 0));
    var m = Math.floor(s / 60), h = Math.floor(m / 60);
    var mm = h ? String(m % 60).padStart(2, "0") : String(m);
    return (h ? h + ":" : "") + mm + ":" + String(s % 60).padStart(2, "0");
  }

  function post(url, body) {
    var payload = JSON.stringify(body);
    if (navigator.sendBeacon) {
      navigator.sendBeacon(url, new Blob([payload], { type: "application/json" }));
      return;
    }
    fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: payload,
      keepalive: true,
    }).catch(function () { /* offline is not an error worth shouting about */ });
  }

  function savePosition(seconds) {
    if (!RID) return;
    post("/resource/" + RID + "/position", { seconds: Math.floor(seconds) });
    lastSavedAt = seconds;
  }

  function creditMinutes() {
    var whole = Math.floor(watchedSecs / 60);
    if (whole <= creditedMin || !UNIT) return;
    var delta = whole - creditedMin;
    creditedMin = whole;
    post("/unit/" + UNIT + "/log-auto", { minutes: delta });
    if (status) status.textContent = creditedMin + " min logged automatically";
  }

  function markWatched() {
    if (marked || !RID) return;
    marked = true;
    post("/resource/" + RID + "/watched", { done: true });
    if (status) {
      status.textContent = "Marked as watched";
      status.classList.add("live");
    }
    var toggle = document.querySelector("[data-watched-label]");
    if (toggle) toggle.textContent = "Undo “watched”";
  }

  function tick() {
    if (!yt || !yt.getCurrentTime) return;
    var t = yt.getCurrentTime() || 0;
    var d = yt.getDuration() || 0;

    if (fill && d) fill.style.width = ((t / d) * 100).toFixed(2) + "%";
    if (clock) clock.textContent = fmt(t) + (d ? " / " + fmt(d) : "");
    if (openLink) openLink.href = watchUrl(Math.floor(t));

    watchedSecs += 1;
    creditMinutes();

    if (t - lastSavedAt >= 5 || lastSavedAt - t > 5) savePosition(t);
    if (d && t / d >= 0.9) markWatched();
  }

  function watchUrl(at) {
    var u = LIST_ID && !VIDEO_ID
      ? "https://www.youtube.com/playlist?list=" + LIST_ID
      : "https://www.youtube.com/watch?v=" + (currentVideoId() || VIDEO_ID);
    if (LIST_ID && VIDEO_ID) u += "&list=" + LIST_ID;
    if (at > 0 && u.indexOf("/watch") > -1) u += "&t=" + at + "s";
    return u;
  }

  function currentVideoId() {
    try {
      var d = yt && yt.getVideoData && yt.getVideoData();
      return (d && d.video_id) || "";
    } catch (e) { return ""; }
  }

  // --- playlist rail ------------------------------------------------------
  // Built from the playlist YouTube actually returns, so it can never drift
  // out of sync with a hand-maintained list in the curriculum YAML.
  function buildRail() {
    if (!railBox || !yt || !yt.getPlaylist) return;
    var ids = yt.getPlaylist();
    if (!ids || ids.length < 2) return;

    var ol = document.createElement("ol");
    ids.forEach(function (id, i) {
      var li = document.createElement("li");
      var b = document.createElement("button");
      b.type = "button";
      b.innerHTML = '<span class="n">' + (i + 1) + "</span><span>Part " + (i + 1) + "</span>";
      b.addEventListener("click", function () {
        yt.playVideoAt(i);
        syncRail();
      });
      li.appendChild(b);
      ol.appendChild(li);
    });

    railBox.innerHTML =
      '<p class="head"><span>In this playlist</span><span>' + ids.length + "</span></p>";
    railBox.appendChild(ol);
    railBox.hidden = false;
    syncRail();
  }

  function syncRail() {
    if (!railBox || !yt || !yt.getPlaylistIndex) return;
    var idx = yt.getPlaylistIndex();
    var items = railBox.querySelectorAll("li");
    for (var i = 0; i < items.length; i++) {
      items[i].setAttribute("aria-current", i === idx ? "true" : "false");
    }
    var here = items[idx];
    if (here && here.scrollIntoView) here.scrollIntoView({ block: "nearest" });
  }

  // --- boot ---------------------------------------------------------------
  function start() {
    if (yt) { yt.playVideo(); return; }
    if (poster) poster.hidden = true;

    var vars = {
      autoplay: 1,
      rel: 0,
      modestbranding: 1,
      playsinline: 1,
      origin: window.location.origin,
    };
    if (START_AT > 0) vars.start = START_AT;
    if (LIST_ID) { vars.list = LIST_ID; vars.listType = "playlist"; }

    yt = new YT.Player("stage-mount", {
      videoId: VIDEO_ID || undefined,
      playerVars: vars,
      events: {
        onReady: function () {
          if (START_AT > 0 && yt.seekTo) yt.seekTo(START_AT, true);
          buildRail();
        },
        onStateChange: function (e) {
          var playing = e.data === YT.PlayerState.PLAYING;
          root.classList.toggle("is-playing", playing);
          if (playing && !ticker) ticker = setInterval(tick, 1000);
          if (!playing && ticker) { clearInterval(ticker); ticker = null; }
          if (e.data === YT.PlayerState.ENDED) markWatched();
          syncRail();
        },
      },
    });
  }

  // The API script is only fetched once you press play, so the unit page still
  // loads instantly - and offline - when you are only there for the notes.
  var apiLoading = false;
  function loadApi(then) {
    if (window.YT && window.YT.Player) return then();
    if (!apiLoading) {
      apiLoading = true;
      var s = document.createElement("script");
      s.src = "https://www.youtube.com/iframe_api";
      document.head.appendChild(s);
    }
    var prev = window.onYouTubeIframeAPIReady;
    window.onYouTubeIframeAPIReady = function () {
      if (prev) prev();
      then();
    };
  }
  if (poster) {
    poster.addEventListener("click", function (e) {
      e.preventDefault();
      loadApi(start);
    }, { once: true });
  }

  // --- keyboard -----------------------------------------------------------
  document.addEventListener("keydown", function (e) {
    if (!yt || e.metaKey || e.ctrlKey || e.altKey) return;
    var el = document.activeElement;
    if (el && /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName)) return;

    var t = yt.getCurrentTime ? yt.getCurrentTime() : 0;
    switch (e.key) {
      case "k": case " ":
        e.preventDefault();
        yt.getPlayerState() === 1 ? yt.pauseVideo() : yt.playVideo();
        break;
      case "j": e.preventDefault(); yt.seekTo(Math.max(0, t - 10), true); break;
      case "l": e.preventDefault(); yt.seekTo(t + 10, true); break;
      case ",": if (yt.previousVideo) yt.previousVideo(); break;
      case ".": if (yt.nextVideo) yt.nextVideo(); break;
      default: return;
    }
  });

  // --- leaving the page ---------------------------------------------------
  window.addEventListener("pagehide", function () {
    if (!yt || !yt.getCurrentTime) return;
    savePosition(yt.getCurrentTime());
    creditMinutes();
  });
})();
