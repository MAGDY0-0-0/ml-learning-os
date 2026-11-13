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

  /* What follows part `at` once it has ended: the next part, or the end of
     what this unit asks you to watch. Pure, so it is tested without a browser
     (tests/test_named_videos.py).

     A part ends when YouTube ends its clip (see goToSegment), never by this
     page watching the clock. Watching the clock once a second missed parts
     that run to their video's last second, and two triggers -- the clock and
     the clip's own end -- could both fire and skip a part. */
  function afterPart(segs, at) {
    var next = segs[at + 1];
    if (!segs[at] || !next) return { action: "stop" };
    return { action: "next", at: at + 1, video: next.video, from: next.from || 0 };
  }

  /* Which segment to resume in: the one whose video you were last watching. */
  function resumeSegment(segs, saved) {
    if (!saved || !saved.video) return 0;
    for (var i = 0; i < segs.length; i++) if (segs[i].video === saved.video) return i;
    return 0;
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = { afterPart: afterPart, resumeSegment: resumeSegment };
  }
  if (typeof document === "undefined") return;

  var root = document.getElementById("player");
  if (!root) return;

  var RID       = root.dataset.resourceId;
  var UNIT      = root.dataset.unitSlug;
  var VIDEO_ID  = root.dataset.videoId || "";
  var LIST_ID   = root.dataset.listId || "";
  var START_AT  = parseInt(root.dataset.startAt || "0", 10) || 0;

  /* The part of this video the unit actually asks for: {video, from, to}.
     `video` matters because most primaries here are playlists, where a bare
     timestamp means nothing — it tells us which entry to jump to first. */
  var SEGS = [];
  try { SEGS = JSON.parse(root.dataset.segments || "[]") || []; } catch (e) { SEGS = []; }
  var segAt = 0;                 // which segment we are inside
  var segDone = false;           // past the last one
  function SEG() { return SEGS[segAt] || null; }
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

  /* The server keeps one number per resource: seconds. On a unit made of
     several named videos that number means nothing without the video it
     belongs to, so the video is kept beside it, on this machine. */
  var PLACE_KEY = "mlos-place-" + RID;
  function savedPlace() {
    try { return JSON.parse(localStorage.getItem(PLACE_KEY) || "null"); } catch (e) { return null; }
  }

  function savePosition(seconds) {
    if (!RID) return;
    post("/resource/" + RID + "/position", { seconds: Math.floor(seconds) });
    lastSavedAt = seconds;
    var vid = currentVideoId();
    if (SEGS.length > 1 && vid) {
      try { localStorage.setItem(PLACE_KEY, JSON.stringify({ video: vid, seconds: Math.floor(seconds) })); } catch (e) { /* private mode */ }
    }
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

    if (d && !SEGS.length && t / d >= 0.9) markWatched();
  }

  /* Every part is played as a clip: its own video, its own start, and its
     own end, which YouTube enforces and then reports as "ended". Watching a
     playlist and checking the clock once a second missed parts that run to
     the last second of their video -- the playlist rolled straight on into an
     unrelated video -- and a background tab can slow that check to once a
     minute. The player's own end is exact, whatever the tab is doing. */
  function clip(seg, from) {
    var c = { videoId: seg.video || VIDEO_ID, startSeconds: from };
    if (seg.to != null) c.endSeconds = seg.to;
    return c;
  }

  /* YouTube can report "ended" for a clip a second time, after the next one
     has already been asked for -- seen in testing, where it marked a whole
     unit done six seconds into its last part. An end only counts once this
     part has actually played, and when the clock is at the part's end. */
  var partPlaying = false;
  function atPartEnd() {
    var seg = SEG();
    if (!partPlaying || !seg || !yt.getCurrentTime) return false;
    var end = seg.to != null ? seg.to : (yt.getDuration ? yt.getDuration() : 0);
    return !end || (yt.getCurrentTime() || 0) >= end - 3;
  }

  function goToSegment(i, from) {
    var seg = SEGS[i];
    if (!seg || !yt) return;
    segAt = i;
    segDone = false;
    partPlaying = false;
    yt.loadVideoById(clip(seg, from != null ? from : (seg.from || 0)));
    if (status) {
      status.textContent = "Part " + (i + 1) + " of " + SEGS.length + ": " + seg.title;
      status.classList.add("live");
    }
    syncRail();
  }

  function watchUrl(at) {
    // Prefer whatever is actually on screen. On a playlist-primary unit there
    // is no video id up front, so the only way to hand YouTube your real place
    // -- the right entry of 106, at the right second -- is to ask the player.
    var id = currentVideoId() || VIDEO_ID;
    if (!id) return "https://www.youtube.com/playlist?list=" + LIST_ID;

    var u = "https://www.youtube.com/watch?v=" + id;
    if (LIST_ID) u += "&list=" + LIST_ID;
    if (at > 0) u += "&t=" + Math.floor(at) + "s";
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
    if (!railBox || !yt) return;
    if (SEGS.length > 1) return buildSegmentRail();
    if (!yt.getPlaylist) return;
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

  // When the unit names its parts, the rail lists those parts by title --
  // the same list the briefing showed -- rather than every video in a
  // playlist that may hold a hundred and fifty.
  function buildSegmentRail() {
    var ol = document.createElement("ol");
    SEGS.forEach(function (seg, i) {
      var li = document.createElement("li");
      var b = document.createElement("button");
      b.type = "button";
      var mins = seg.to != null ? Math.max(1, Math.round((seg.to - (seg.from || 0)) / 60)) + " min" : "";
      b.innerHTML = '<span class="n">' + (i + 1) + '</span><span class="t"></span><span class="m">' + mins + "</span>";
      b.querySelector(".t").textContent = seg.title;
      b.addEventListener("click", function () { goToSegment(i); });
      li.appendChild(b);
      ol.appendChild(li);
    });
    railBox.innerHTML = '<p class="head"><span>The parts of this unit</span><span>' + SEGS.length + "</span></p>";
    railBox.appendChild(ol);
    railBox.hidden = false;
    syncRail();
  }

  function syncRail() {
    if (!railBox || !yt) return;
    if (SEGS.length > 1) {
      var parts = railBox.querySelectorAll("li");
      for (var k = 0; k < parts.length; k++) parts[k].setAttribute("aria-current", k === segAt ? "true" : "false");
      return;
    }
    if (!yt.getPlaylistIndex) return;
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
    var startVideo = VIDEO_ID;
    if (SEGS.length) {
      // On a unit of several named videos, the saved seconds belong to the
      // video you were last in; pick up there, not at that second of part one.
      if (SEGS.length > 1) {
        var place = savedPlace();
        segAt = resumeSegment(SEGS, place);
        START_AT = place && place.video === SEG().video ? place.seconds : 0;
      }
      var seg = SEG();
      if (!START_AT || START_AT < (seg.from || 0) || (seg.to != null && START_AT >= seg.to)) {
        START_AT = seg.from || 0;
      }
      startVideo = seg.video || VIDEO_ID;
      if (seg.to != null) vars.end = seg.to;
    } else if (LIST_ID) {
      vars.list = LIST_ID;
      vars.listType = "playlist";
    }
    if (START_AT > 0) vars.start = START_AT;

    // A playlist has no video id, and the API rejects the *key* being present
    // at all -- `videoId: undefined` still throws "Invalid video id", which
    // took out every playlist-primary unit. Build the config without it.
    var config = { playerVars: vars, events: {} };
    if (startVideo) config.videoId = startVideo;

    config.events = {
        onReady: function () {
          if (START_AT > 0 && yt.seekTo) yt.seekTo(START_AT, true);
          buildRail();
        },
        onStateChange: function (e) {
          var playing = e.data === YT.PlayerState.PLAYING;
          root.classList.toggle("is-playing", playing);
          if (playing && SEGS.length && currentVideoId() === (SEG().video || VIDEO_ID)) partPlaying = true;
          if (playing && !ticker) ticker = setInterval(tick, 1000);
          if (!playing && ticker) { clearInterval(ticker); ticker = null; }
          if (e.data === YT.PlayerState.ENDED) {
            if (!SEGS.length) { markWatched(); }
            else if (!segDone && atPartEnd()) {
              var after = afterPart(SEGS, segAt);
              // More than one part earns its place in this unit: go straight
              // to the next one rather than making you find it.
              if (after.action === "next") { goToSegment(after.at); return; }
              // The unit asked for this much and no more. Stop, rather than
              // rolling on into the hours it deliberately left out.
              segDone = true;
              markWatched();
              if (status) { status.textContent = "That's the part — done"; status.classList.add("live"); }
            }
          }
          syncRail();
        },
      onError: function (e) { showFailure(e.data); },
    };

    yt = new YT.Player("stage-mount", config);
  }

  // --- when the video will not play -------------------------------------
  // Without this the stage is simply black and silent. Videos get removed,
  // set to private, or have embedding switched off by their owner long after
  // a curriculum is written, and the last of those is common enough that most
  // people meet it eventually. Say which it is, and offer the way out.
  var FAILURES = {
    2:   ["That video link is malformed.",
          "The id in the curriculum is not a valid YouTube id."],
    5:   ["This video will not play in the browser's player.",
          "An HTML5 playback error — it usually still plays on YouTube itself."],
    100: ["This video is gone.",
          "It has been removed, or made private, since the curriculum was written."],
    // 101 and 150 are the same error under two names, and YouTube overloads
    // them: they mean "embedding is switched off" *and* "no such video". Tested
    // against a nonexistent id, which reports 150 — so this copy must not
    // promise that it plays on YouTube, because sometimes it does not.
    101: ["This video will not play inside the app.",
          "Its owner has switched off embedding, or it is no longer available. " +
          "Opening it on YouTube will tell you which."],
  };
  FAILURES[150] = FAILURES[101];

  function showFailure(code) {
    if (ticker) { clearInterval(ticker); ticker = null; }
    root.classList.remove("is-playing");

    var f = FAILURES[code] || ["This video would not load.",
                               "YouTube returned error " + code + "."];
    var stage = root.querySelector(".stage");
    if (!stage) return;

    stage.innerHTML =
      '<div class="stage-fail">' +
        '<svg class="i" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
          'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" ' +
          'aria-hidden="true"><use href="#ic-alert"/></svg>' +
        '<p class="t"></p><p class="s"></p>' +
        '<div class="acts">' +
          '<a class="btn watch" target="_blank" rel="noopener">Watch on YouTube ↗</a>' +
          '<button class="btn" type="button" data-open-alts>Try a different teacher</button>' +
        '</div>' +
      "</div>";

    stage.querySelector(".t").textContent = f[0];
    stage.querySelector(".s").textContent = f[1];
    stage.querySelector("a").href = watchUrl(0);

    var status = root.querySelector("[data-status]");
    if (status) { status.textContent = "Could not play"; status.classList.add("bad"); }
  }

  // A dead video should land you in the swap flow, not at a dead end.
  document.addEventListener("click", function (e) {
    if (!e.target.closest("[data-open-alts]")) return;
    var alts = document.querySelector("details.alts");
    if (!alts) return;
    alts.open = true;
    alts.scrollIntoView({ behavior: "smooth", block: "start" });
  });

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

  // --- lesson steps -------------------------------------------------------
  // The player lives in the Learn step. Moving to another step hides it, so
  // stop the sound and save the position rather than play on unseen.
  function inLearn() {
    var step = document.documentElement.getAttribute("data-step");
    return !step || step === "learn";
  }
  window.addEventListener("lesson:step", function (e) {
    if (!yt || !yt.getPlayerState || (e.detail && e.detail.step === "learn")) return;
    if (yt.getPlayerState() === 1) {
      yt.pauseVideo();
      if (yt.getCurrentTime) savePosition(yt.getCurrentTime());
    }
  });

  // --- keyboard -----------------------------------------------------------
  document.addEventListener("keydown", function (e) {
    if (!yt || e.metaKey || e.ctrlKey || e.altKey || !inLearn()) return;
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
      case ",":
        if (SEGS.length > 1) { if (segAt > 0) goToSegment(segAt - 1); }
        else if (yt.previousVideo) yt.previousVideo();
        break;
      case ".":
        if (SEGS.length > 1) { if (segAt < SEGS.length - 1) goToSegment(segAt + 1); }
        else if (yt.nextVideo) yt.nextVideo();
        break;
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
