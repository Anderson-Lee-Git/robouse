/* robouse.ai/runs viewer: task filters, the trial page (recording synced to the steps, filmstrip, trajectory,
   verdict, timing and tokens, files) and the compare view. No dependencies; data comes from /runs/d/<trial>.json. */
(function () {
  "use strict";
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return [].slice.call((r || document).querySelectorAll(s)); };
  function h(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]; }); }
  function t2(x) { x = +x || 0; var m = Math.floor(x / 60), s = x - m * 60; return m + ":" + (s < 10 ? "0" : "") + s.toFixed(1); }
  function dur(x) { if (x == null) return "–"; x = +x; return x < 120 ? x.toFixed(x < 10 ? 1 : 0) + " s" : (x / 60).toFixed(1) + " min"; }
  function num(x) { return x == null ? "–" : Number(x).toLocaleString("en-US"); }
  function kfmt(x) { x = +x || 0; return x >= 1e6 ? (x / 1e6).toFixed(2) + "M" : x >= 1e4 ? Math.round(x / 1e3) + "k" : x >= 1e3 ? (x / 1e3).toFixed(1) + "k" : String(x); }
  function getJSON(u) { return fetch(u).then(function (r) { if (!r.ok) throw new Error(r.status + " " + u); return r.json(); }); }
  var STATUS = {ok: "Solved", no: "Not solved", infra: "Infra failure", partial: "Partial"};

  /* ---------------------------------------------------------------- tooltip */
  var tip;
  function showTip(e, text) {
    if (!tip) { tip = document.createElement("div"); tip.className = "tip"; document.body.appendChild(tip); }
    tip.textContent = text; tip.style.display = "block";
    var x = Math.min(e.clientX + 12, window.innerWidth - tip.offsetWidth - 8), y = e.clientY + 14;
    if (y + tip.offsetHeight > window.innerHeight - 8) y = e.clientY - tip.offsetHeight - 10;
    tip.style.left = x + "px"; tip.style.top = y + "px";
  }
  function hideTip() { if (tip) tip.style.display = "none"; }
  document.addEventListener("mousemove", function (e) {
    var el = e.target.closest && e.target.closest("[data-tip]");
    if (el) showTip(e, el.getAttribute("data-tip")); else hideTip();
  });

  /* ---------------------------------------------------------------- tasks table */
  function initTasks(table) {
    var params = new URLSearchParams(location.search);
    var state = {suite: params.get("s") || "", model: params.get("m") || "", outcome: params.get("o") || "", q: params.get("q") || ""};
    var rows = $$("tbody tr", table).map(function (tr) {
      var st = {};
      tr.getAttribute("data-st").split(" ").forEach(function (p) { var i = p.lastIndexOf(":"); st[p.slice(0, i)] = p.slice(i + 1); });
      return {tr: tr, suite: tr.getAttribute("data-suite"), q: tr.getAttribute("data-q"), st: st};
    });
    var heads = $$("thead th", table), colIndex = {};
    heads.forEach(function (th, i) { if (th.getAttribute("data-col")) colIndex[th.getAttribute("data-col")] = i; });
    var sel = {model: $('[data-f="model"]'), outcome: $('[data-f="outcome"]'), q: $('[data-f="q"]')};
    if (sel.model) sel.model.value = state.model;
    if (sel.outcome) sel.outcome.value = state.outcome;
    if (sel.q) sel.q.value = state.q;
    var chips = $$(".chips button");
    function apply() {
      chips.forEach(function (b) { b.setAttribute("aria-pressed", b.getAttribute("data-suite") === state.suite ? "true" : "false"); });
      var shown = 0;
      rows.forEach(function (r) {
        var ok = !state.suite || r.suite === state.suite;
        if (ok && state.q) ok = r.q.indexOf(state.q.toLowerCase()) >= 0;
        if (ok && state.outcome) {
          var vals = Object.keys(r.st).map(function (k) { return r.st[k]; });
          if (state.outcome === "split") {
            ok = vals.indexOf("ok") >= 0 && vals.indexOf("no") >= 0;
          } else if (state.model) {
            ok = r.st[state.model] === state.outcome;
          } else {
            ok = vals.indexOf(state.outcome) >= 0;
          }
        }
        r.tr.hidden = !ok; if (ok) shown++;
      });
      var ci = state.model ? colIndex[state.model] : -1;
      $$(".hl", table).forEach(function (c) { c.classList.remove("hl"); });
      if (ci >= 0) {
        heads[ci].classList.add("hl");
        rows.forEach(function (r) { var c = r.tr.children[ci]; if (c) c.classList.add("hl"); });
      }
      var cnt = $("[data-count]"); if (cnt) cnt.textContent = shown + " of " + rows.length + " tasks";
      var p = new URLSearchParams();
      if (state.suite) p.set("s", state.suite);
      if (state.model) p.set("m", state.model);
      if (state.outcome) p.set("o", state.outcome);
      if (state.q) p.set("q", state.q);
      var qs = p.toString();
      history.replaceState(null, "", location.pathname + (qs ? "?" + qs : "") + location.hash);
    }
    chips.forEach(function (b) { b.addEventListener("click", function () { state.suite = b.getAttribute("data-suite"); apply(); }); });
    ["model", "outcome"].forEach(function (k) { if (sel[k]) sel[k].addEventListener("change", function () { state[k] = sel[k].value; apply(); }); });
    if (sel.q) sel.q.addEventListener("input", function () { state.q = sel.q.value.trim(); apply(); });
    apply();
    if (state.model && location.hash !== "#tasks" && document.body.classList.contains("suite")) { /* highlighted column is enough */ }
  }

  /* ---------------------------------------------------------------- shared step helpers */
  function actionOf(s) {
    if (s.c && s.c.length) {
      var a = s.c[0].a.split("\n")[0];
      return {text: a + (s.c.length > 1 ? "  (+" + (s.c.length - 1) + ")" : ""), cls: ""};
    }
    if (s.src === "system") return {text: (s.m || "").split("\n")[0], cls: "sys"};
    return {text: (s.m || s.r || "").replace(/\s+/g, " "), cls: "msg"};
  }
  function exitOf(s) { return (s.c || []).some(function (c) { return c.x != null; }); }
  function sprStyle(sp, i, size) {
    size = size || sp.tile;
    var k = size / sp.tile, cols = Math.min(sp.n, sp.cols), rows = Math.ceil(sp.n / sp.cols);
    return "background-image:url(" + sp.src + ");background-size:" + (cols * sp.tile * k) + "px " + (rows * sp.tile * k) + "px;background-position:-" +
      ((i % sp.cols) * sp.tile * k) + "px -" + (Math.floor(i / sp.cols) * sp.tile * k) + "px";
  }
  function stepListHTML(d) {
    return d.steps.map(function (s) {
      var a = actionOf(s), v = s.v;
      var x = s.env && s.env[1] > s.env[0] ? "+" + (s.env[1] - s.env[0]) + " steps" : "";
      return '<li data-i="' + s.i + '"' + (v ? ' data-t0="' + v[0] + '"' : ' class="nov"') + '><span class="i">' + s.i + '</span><span class="t">' + (v ? t2(v[0]) : "") +
        '</span><span class="a ' + a.cls + '" title="' + h(a.text.slice(0, 400)) + '">' + h(a.text.slice(0, 220)) + '</span><span class="x' + (exitOf(s) ? " err" : "") + '">' + (exitOf(s) ? "exit≠0" : x) + "</span></li>";
    }).join("");
  }

  /* Video <-> step sync. steps: [{i, t0}] sorted by t0; onStep(i) is called when the current step changes. */
  function syncVideo(v, d, onStep) {
    var marks = d.steps.filter(function (s) { return s.v; }).map(function (s) { return {i: s.i, t0: +s.v[0]}; });
    var cur = null, raf = 0, pinned = null;
    function at(t) {
      var hit = null;
      for (var k = 0; k < marks.length; k++) { if (marks[k].t0 <= t + 0.02) hit = marks[k].i; else break; }
      if (pinned) {  /* several steps can share one video time: keep the one the user picked until the video moves on */
        var p = marks.find(function (m) { return m.i === pinned; });
        var hitT = marks.find(function (m) { return m.i === hit; });
        if (p && hitT && Math.abs(hitT.t0 - p.t0) < 0.021 && t < p.t0 + 0.2) return pinned;
        pinned = null;
      }
      return hit;
    }
    function tick() {
      var i = at(v.currentTime);
      if (i !== cur) { cur = i; onStep(i); }
      if (!v.paused) raf = requestAnimationFrame(tick);
    }
    v.addEventListener("play", function () { cancelAnimationFrame(raf); raf = requestAnimationFrame(tick); });
    v.addEventListener("seeked", tick);
    v.addEventListener("timeupdate", function () { var i = at(v.currentTime); if (i !== cur) { cur = i; onStep(i); } });
    return {marks: marks, now: function () { return cur; }, tick: tick, pin: function (i) { pinned = i == null ? null : +i; }};
  }

  function seekTo(v, t) {
    if (!v) return;
    t = Math.max(0, +t || 0);
    var go = function () { v.currentTime = Math.min(t + 0.001, (v.duration || t + 1) - 0.001); };
    if (v.readyState >= 1) go(); else v.addEventListener("loadedmetadata", go, {once: true});
  }

  /* ---------------------------------------------------------------- trial page */
  function initTrial(id) {
    var stage = $("#stage"), panel = $("#panel"), player = $("#player"), v = $("#vid");
    var below = document.createElement("div"); below.id = "below"; stage.parentNode.insertBefore(below, stage.nextSibling);
    getJSON("/runs/d/" + id + ".json").then(function (d) {
      var tabs = $$("nav.tabs a"), current = null, sync = null, playerExtras = null;
      var SPEEDS = [0.25, 0.5, 1];
      var speed = +(localStorage.getItem("runs-speed") || 0.5);
      if (v) {
        v.playbackRate = speed;
        v.addEventListener("loadedmetadata", function () { v.playbackRate = speed; });
        playerExtras = document.createElement("div");
        var lane = '<div class="lane" title="steps with robot motion; blue: camera images">' +
          d.steps.filter(function (s) { return s.v && s.robo; }).map(function (s) {
            return '<i style="left:' + pct(s.v[0]) + '%"' + (hasImg(s) ? ' class="im"' : "") + "></i>";
          }).join("") + '<b style="left:0"></b></div>';
        playerExtras.innerHTML = lane + '<div class="ctl"><button type="button" data-k="prev" title="previous step (←)">◀</button><button type="button" data-k="play" title="play / pause (space)">Play</button>' +
          '<button type="button" data-k="next" title="next step (→)">▶</button>' +
          SPEEDS.map(function (s) { return '<button type="button" data-speed="' + s + '" aria-pressed="' + (s === speed) + '">' + s + "×</button>"; }).join("") +
          '<span class="now"></span></div><p class="cap">Simulation recording: it has only the moments the robot moved, not the agent’s thinking time.</p>';
        player.appendChild(playerExtras);
        var knob = $(".lane b", playerExtras), laneEl = $(".lane", playerExtras), now = $(".now", playerExtras), playB = $('[data-k="play"]', playerExtras);
        v.addEventListener("timeupdate", function () { knob.style.left = pct(v.currentTime) + "%"; });
        v.addEventListener("play", function () { playB.textContent = "Pause"; });
        v.addEventListener("pause", function () { playB.textContent = "Play"; });
        laneEl.addEventListener("click", function (e) { var r = laneEl.getBoundingClientRect(); seekTo(v, (e.clientX - r.left) / r.width * dur0()); });
        playerExtras.addEventListener("click", function (e) {
          var b = e.target.closest("button"); if (!b) return;
          if (b.hasAttribute("data-speed")) {
            speed = +b.getAttribute("data-speed"); v.playbackRate = speed; localStorage.setItem("runs-speed", speed);
            $$("[data-speed]", playerExtras).forEach(function (x) { x.setAttribute("aria-pressed", x === b ? "true" : "false"); });
          } else if (b.getAttribute("data-k") === "play") { if (v.paused) v.play(); else v.pause(); }
          else step(b.getAttribute("data-k") === "next" ? 1 : -1);
        });
        sync = syncVideo(v, d, function (i) {
          $$(".cur[data-i]").forEach(function (el) { el.classList.remove("cur"); });
          if (i == null) { now.textContent = ""; return; }
          $$('[data-i="' + i + '"]').forEach(function (el) { el.classList.add("cur"); });
          var s = d.steps.find(function (x) { return x.i === i; });
          now.textContent = "step " + i + (s ? " · " + actionOf(s).text.slice(0, 60) : "");
          var li = $('.slist li[data-i="' + i + '"]');
          if (li) { var box = li.parentNode; var top = li.offsetTop - box.offsetTop; if (top < box.scrollTop || top > box.scrollTop + box.clientHeight - 40) box.scrollTop = top - box.clientHeight / 3; }
          markTiles(i);
        });
        document.addEventListener("keydown", function (e) {
          if (/INPUT|SELECT|TEXTAREA/.test((e.target || {}).tagName || "") || e.metaKey || e.ctrlKey) return;
          if (e.key === "ArrowRight") { step(1); e.preventDefault(); }
          else if (e.key === "ArrowLeft") { step(-1); e.preventDefault(); }
          else if (e.key === " " && current !== "files") { if (v.paused) v.play(); else v.pause(); e.preventDefault(); }
        });
      }
      function dur0() { return (v && v.duration && isFinite(v.duration)) ? v.duration : (d.duration || 1); }
      function pct(t) { return Math.max(0, Math.min(100, 100 * t / dur0())); }
      function hasImg(s) { return (s.c || []).some(function (c) { return c.img && c.img.length; }); }
      function step(dir) {
        if (!sync || !sync.marks.length) return;
        var cur = sync.now(), k = sync.marks.findIndex(function (m) { return m.i === cur; });
        k = Math.max(0, Math.min(sync.marks.length - 1, k + dir));
        v.pause(); sync.pin(sync.marks[k].i); seekTo(v, sync.marks[k].t0);
      }
      function markTiles(i) {
        var best = null;
        $$(".tile[data-s]").forEach(function (t) { var s = +t.getAttribute("data-s"); if (s <= i && (best == null || s >= +best.getAttribute("data-s"))) best = t; t.classList.remove("cur"); });
        if (best) best.classList.add("cur");
      }
      document.addEventListener("click", function (e) {
        var el = e.target.closest && e.target.closest("[data-t0], [data-seek]");
        if (!el || !v || !panel.contains(el) && !below.contains(el)) return;
        if (e.target.closest("a, summary, pre, details .txt")) return;
        var pin = el.getAttribute("data-i") || el.getAttribute("data-s") || (el.closest("[data-i]") || {getAttribute: function () { return null; }}).getAttribute("data-i");
        if (sync) sync.pin(pin);
        if (el.classList.contains("tile") && !(sync && sync.marks.length)) { $$(".tile.cur").forEach(function (t) { t.classList.remove("cur"); }); el.classList.add("cur"); }
        seekTo(v, el.getAttribute("data-seek") || el.getAttribute("data-t0"));
      });

      function show(tab) {
        if (!/^(recording|trajectory|verdict|run|files)$/.test(tab)) tab = "recording";
        current = tab;
        tabs.forEach(function (a) { a.setAttribute("aria-selected", a.getAttribute("data-tab") === tab ? "true" : "false"); });
        stage.className = "stage t-" + tab;
        if (v && (tab === "run" || tab === "files")) v.pause();
        below.innerHTML = "";
        panel.innerHTML = ({recording: recording, trajectory: trajectory, verdict: verdict, run: run, files: files})[tab]();
        if (tab === "recording" && d.sprite) below.innerHTML = strip();
        if (tab === "run") bindRun();
        if (sync) { var i = sync.now(); if (i != null) { $$('[data-i="' + i + '"]').forEach(function (el) { el.classList.add("cur"); }); markTiles(i); } }
      }
      tabs.forEach(function (a) { a.addEventListener("click", function (e) { e.preventDefault(); history.replaceState(null, "", "#" + a.getAttribute("data-tab")); show(a.getAttribute("data-tab")); }); });
      window.addEventListener("hashchange", function () { show(location.hash.slice(1)); });

      function withheldNote() {
        return '<p class="withheld">Trajectory not published: during this trial the agent looked at files outside its workspace (for example listing the home folder or searching the whole disk), so its commands and their outputs may show unrelated local files. The recording, the camera images, the reward and the outcome are shown.</p>';
      }
      function recording() {
        if (d.withheld) return withheldNote();
        if (!d.steps.length) return '<p class="muted">No trajectory was recorded for this trial.</p>';
        var n = d.steps.filter(function (s) { return s.v; }).length;
        return '<div class="rechead"><span>Steps · click to seek</span><span>' + n + " steps · ← → to step</span></div><ol class=\"slist\">" + stepListHTML(d) + "</ol>" +
          (d.hidden ? '<p class="muted small">' + d.hidden + " one-action steps in the middle are not listed.</p>" : "");
      }
      function strip() {
        var sp = d.sprite;
        return '<section class="strip" id="filmstrip"><div class="rechead"><span>Camera images the agent looked at</span><span>' +
          (sp.total > sp.n ? sp.n + " of " + sp.total + " shown" : sp.total) + "</span></div><div class=\"tiles\">" +
          d.obs.map(function (o) {
            return '<button type="button" class="tile"' + (o[1] != null ? ' data-s="' + o[1] + '"' : "") + (o[3] != null ? ' data-seek="' + o[3] + '"' : "") + ' title="' + h(o[0]) + '"><i style="' + sprStyle(sp, o[2]) + '"></i>' + (o[1] != null ? "step " + o[1] : h(o[0].replace(/\.png$/, ""))) + "</button>";
          }).join("") + "</div></section>";
      }
      function trajectory() {
        var out = [];
        if (d.prompt) out.push('<details class="prompt"><summary>Task prompt</summary><div class="txt">' + h(d.prompt) + "</div></details>");
        if (d.withheld) return out.join("") + withheldNote();
        if (!d.steps.length) return out.join("") + '<p class="muted">No trajectory was recorded for this trial.</p>';
        out.push('<ol class="traj">');
        var prev = null;
        d.steps.forEach(function (s) {
          if (d.hidden && prev != null && s.i - prev > 1) out.push('<li class="gap">… ' + d.hidden + " one-action steps not shown …</li>");
          prev = s.i;
          var head = '<div class="sh"><span>' + s.i + '</span><span class="src">' + ({agent: "Agent", system: "System", user: "Prompt"}[s.src] || h(s.src)) + "</span>" +
            (s.ts != null ? "<span>+" + dur(s.ts) + "</span>" : "") + (s.tk ? '<span title="prompt / output tokens">' + kfmt(s.tk[0]) + " / " + kfmt(s.tk[1]) + " tok</span>" : "") +
            (s.v ? '<button type="button" class="seek" data-seek="' + s.v[0] + '" title="seek the video here">' + t2(s.v[0]) + "</button>" : "") + "</div>";
          var body = "";
          if (s.m) body += '<div class="txt">' + h(s.m) + "</div>";
          if (s.r) body += '<details class="rsn"><summary>Reasoning</summary><div class="txt">' + h(s.r) + "</div></details>";
          (s.c || []).forEach(function (c) {
            body += '<pre class="cmd"><code>' + h(c.a) + "</code></pre>";
            if (c.b) body += '<pre class="out"><code>' + h(c.b) + "</code></pre>";
            if (c.img && d.sprite) body += '<div class="imgs">' + c.img.map(function (k) { return '<i style="' + sprStyle(d.sprite, k) + '"></i>'; }).join("") + "</div>";
            if (c.o != null) body += "<details class=\"res\"" + (c.n <= 8 ? " open" : "") + "><summary>Output · " + c.n + " line" + (c.n === 1 ? "" : "s") + (c.x != null ? ' · <span class="x-err">exit ' + h(c.x) + "</span>" : "") + '</summary><pre class="out"><code>' + h(c.o) + "</code></pre></details>";
          });
          out.push('<li class="st ' + h(s.src) + '" data-i="' + s.i + '" id="s' + s.i + '">' + head + body + "</li>");
        });
        out.push("</ol>");
        return out.join("");
      }
      function verdict() {
        var vd = d.verdict, r = d.reward, solved = r != null && r > 0;
        var claim = {done: ["Called robo done", ""], give_up: ["Gave up", "warn"], runner: ["Never called robo done", "warn"], none: ["No robo done or give-up", "warn"]}[vd.claim] || ["–", ""];
        var check = d.status === "partial" ? ["Not scored (partial)", "warn"] : d.status === "infra" ? ["Infrastructure failure", "warn"] : solved ? ["Passed · reward " + r, "ok"] : ["Failed · reward " + (r == null ? "–" : r), "no"];
        var rel = "", relc = "";
        if (d.status === "infra") rel = "The run did not measure the agent (an infrastructure failure), so this trial is not scored.";
        else if (d.status === "partial") rel = "The run was stopped before this trial finished.";
        else if (vd.claim === "done") { rel = solved ? "The agent claimed success, and the simulator agrees." : "The agent claimed success, but the simulator’s check failed."; relc = solved ? "" : "no"; }
        else if (vd.claim === "give_up") rel = solved ? "The agent gave up, and that scored: refusing was the expected answer here." : "The agent gave up; the goal was not reached.";
        else if (vd.claim === "runner") rel = "The agent stopped without robo done or give-up, so the runner closed the episode" + (solved ? "; the final state still satisfied the goal." : ".");
        else rel = d.outcome === "success_reached" ? "The simulator’s success signal fired during the episode, which ended it." : "The episode ended with outcome " + (d.outcome || "–") + ".";
        var mode = {first: "first: success counts as soon as the simulator’s success signal fires", final: "final: after robo done the robot holds still for about 10 steps, then the goal must still hold"}[vd.success_mode] || (vd.success_mode || "–");
        var said = vd.claim_text || vd.last_message;
        var spec = d.spec || {};
        var kv = [["Outcome", d.outcome], ["Success", vd.success == null ? "–" : String(vd.success)], ["Success at any time", vd.success_ever == null ? "–" : String(vd.success_ever)],
          ["Success mode", mode], ["Env steps", num(d.steps_used) + " / " + num(d.max_steps)], ["Robo requests", num(d.requests) + (d.motion != null ? " (" + d.motion + " motion" + (d.robo_errors ? ", " + d.robo_errors + " errors" : "") + ")" : "")],
          ["Backend · env", [spec.backend, spec.env].filter(Boolean).join(" · ")], ["Observation", spec.observation_mode], ["Camera", spec.camera], ["Skills", spec.skills == null ? null : String(spec.skills)], ["Seed", spec.seed], ["Safety", spec.safety]];
        return '<div class="vd">' +
          '<div class="card"><h3>Agent said</h3><p class="big ' + claim[1] + '">' + claim[0] + "</p>" +
          (d.withheld ? '<p class="muted small">Withheld with the trajectory.</p>' : said ? '<div class="txt">' + h(said) + "</div>" + (vd.claim_text ? "" : '<p class="muted small">(its last message)</p>') : '<p class="muted small">No message.</p>') + "</div>" +
          '<div class="card"><h3>Simulator checked</h3><p class="big ' + check[1] + '">' + check[0] + '</p><p class="muted small">The claim never counts: the episode server judges the final physical state.</p>' +
          (vd.verifier ? '<pre class="out"><code>' + h(vd.verifier) + "</code></pre>" : "") + (vd.infra && vd.infra.length ? '<pre class="out"><code>' + h(vd.infra.join("\n")) + "</code></pre>" : "") + "</div>" +
          '<p class="rel ' + relc + '">' + h(rel) + "</p>" +
          '<div class="card" style="grid-column:1/-1"><h3>Episode</h3><dl class="kv">' + kv.filter(function (x) { return x[1] != null && x[1] !== ""; }).map(function (x) { return "<dt>" + h(x[0]) + "</dt><dd>" + h(x[1]) + "</dd>"; }).join("") + "</dl></div></div>";
      }
      function run() {
        var tk = d.tokens, stats = [];
        stats.push(["Wall time", dur(d.wall), "whole run"]);
        stats.push(["Episode", dur(d.ep_wall), ""]);
        stats.push(["Video", d.duration != null ? dur(d.duration) : "–", "robot moving"]);
        stats.push(["Agent steps", num(d.steps.filter(function (s) { return s.src === "agent"; }).length || null), ""]);
        stats.push(["Robo requests", num(d.requests), d.motion != null ? d.motion + " motion" : ""]);
        var envp = d.max_steps ? Math.min(100, 100 * (d.steps_used || 0) / d.max_steps) : 0;
        var html = '<dl class="stats">' + stats.map(function (s) { return "<div><dt>" + s[0] + "</dt><dd>" + s[1] + (s[2] ? "<small>" + s[2] + "</small>" : "") + "</dd></div>"; }).join("") +
          '<div><dt>Env steps</dt><dd>' + num(d.steps_used) + "<small>of " + num(d.max_steps) + '</small></dd><div class="meter"><i style="width:' + envp + '%"></i></div></div>';
        if (tk) {
          html += "<div><dt>Input tokens</dt><dd>" + kfmt(tk["in"]) + (tk.cached ? "<small>" + Math.round(100 * tk.cached / Math.max(1, tk["in"])) + "% cached</small>" : "") + "</dd></div>" +
            "<div><dt>Output tokens</dt><dd>" + kfmt(tk.out) + (tk.reasoning ? "<small>" + kfmt(tk.reasoning) + " reasoning</small>" : "") + "</dd></div>" +
            (tk.cost ? "<div><dt>Cost</dt><dd>$" + tk.cost.toFixed(2) + "</dd></div>" : "");
        }
        html += "</dl>";
        if (d.withheld) return html + withheldNote();
        var ts = d.steps.filter(function (s) { return s.ts != null; });
        if (ts.length > 1) {
          var T = ts[ts.length - 1].ts - ts[0].ts || 1;
          var segs = ts.slice(0, -1).map(function (s, k) {
            var dt = Math.max(0, ts[k + 1].ts - s.ts);
            return '<i style="flex:' + Math.max(dt, T / 2000).toFixed(3) + ' 0 0" data-go="' + ts[k + 1].i + '" data-tip="' + dur(dt) + " before step " + ts[k + 1].i + "\n" + h(actionOf(ts[k + 1]).text.slice(0, 120)) + '"></i>';
          });
          html += '<section class="chart"><h3>Wall clock between steps<span>' + dur(T) + " from the first step to the last; each segment is the time before a step (the previous command running, then the model thinking) · click for the step</span></h3>" +
            '<div class="tl">' + segs.join("") + '</div><div class="axis"><span>0</span><span>' + dur(T / 2) + "</span><span>" + dur(T) + "</span></div></section>";
        }
        var tks = d.steps.filter(function (s) { return s.tk; });
        var outSum = tks.reduce(function (a, s) { return a + s.tk[1]; }, 0), outOk = !tk || outSum >= 0.5 * (tk.out || 0);
        if (tks.length > 1) {
          var maxIn = Math.max.apply(null, tks.map(function (s) { return s.tk[0]; })) || 1, maxOut = Math.max.apply(null, tks.map(function (s) { return s.tk[1]; })) || 1;
          html += '<section class="chart"><h3>Input tokens per step<span>the context the model read, up to ' + kfmt(maxIn) + "</span></h3><div class=\"bars\">" +
            tks.map(function (s) { return '<i style="height:' + (100 * s.tk[0] / maxIn).toFixed(1) + '%" data-go="' + s.i + '" data-tip="step ' + s.i + " · " + num(s.tk[0]) + " input (" + num(s.tk[2]) + ' cached)"></i>'; }).join("") + "</div></section>" +
            (outOk ? '<section class="chart"><h3>Output tokens per step<span>up to ' + kfmt(maxOut) + "</span></h3><div class=\"bars out\">" +
            tks.map(function (s) { return '<i style="height:' + (100 * s.tk[1] / maxOut).toFixed(1) + '%" data-go="' + s.i + '" data-tip="step ' + s.i + " · " + num(s.tk[1]) + ' output"></i>'; }).join("") + "</div></section>"
            : '<p class="muted small">Output tokens per step are not shown: this harness\u2019s per-message counts do not add up to its run total.</p>');
        } else if (tk) {
          html += '<p class="muted small">This harness reports tokens for the whole run only, not per step.</p>';
        }
        return html;
      }
      function bindRun() {
        $$("[data-go]", panel).forEach(function (el) {
          el.addEventListener("click", function () {
            var i = el.getAttribute("data-go"); history.replaceState(null, "", "#trajectory"); show("trajectory");
            var li = document.getElementById("s" + i); if (li) { li.scrollIntoView({block: "center"}); li.classList.add("flash"); setTimeout(function () { li.classList.remove("flash"); }, 1600); }
          });
        });
      }
      function parse(t) { try { return t ? JSON.parse(t) : null; } catch (e) { return null; } }
      function dl(key, label) {  // the sanitized JSON as a small download link, never shown raw
        return '<a class="dl" href="#" data-dl="' + key + '">' + h(label) + "</a>";
      }
      function summary() {
        var r = parse(d.result_json) || {}, c = parse(d.config_json) || {}, ep = r.episode || {}, meta = c.metadata || {};
        var reward = r.verifier_result && r.verifier_result.rewards ? r.verifier_result.rewards.reward : d.reward;
        var who = (c.harness || (r.agent_info || {}).name || "") + (c.model ? " with " + c.model : "");
        var steps = ep.steps_used != null ? num(ep.steps_used) + (ep.max_steps ? " of " + num(ep.max_steps) : "") + " simulator steps" : "";
        var parts = [];
        if (reward != null) parts.push("Reward " + h(reward) + (ep.outcome ? ", outcome " + h(ep.outcome) : ""));
        if (steps) parts.push(steps + (ep.requests != null ? " in " + num(ep.requests) + " robot requests" : ""));
        var wall = r.wall_time_s != null ? dur(r.wall_time_s) : "";
        var agent = [];
        if (r.agent_return_code != null) agent.push("exit code " + h(r.agent_return_code));
        if (r.agent_timed_out) agent.push("timed out");
        if (r.exception_info) agent.push("stopped by an exception");
        var result = '<section class="card sum"><h3>Result</h3><p class="big ' + (reward === 1 || reward === 1.0 ? "ok" : reward === 0 ? "no" : "warn") + '">' + (parts[0] || "Not scored") + "</p>" +
          (parts[1] ? "<p>" + parts[1] + (wall ? ", " + wall + " in all" : "") + ".</p>" : "") +
          (agent.length ? '<p class="muted">Agent: ' + agent.join(", ") + ".</p>" : "") +
          (ep.agent_text ? '<blockquote>' + h(ep.agent_text) + "</blockquote>" : "") +
          '<p class="dls">' + (d.result_json ? dl("result", "Download result.json") : "") + "</p></section>";
        var chips = [meta.source_benchmark, meta.category && meta.category.replace(/-/g, " "), meta.difficulty].filter(Boolean)
          .map(function (x) { return '<span class="chip">' + h(x) + "</span>"; }).join("") +
          (meta.tags || []).map(function (x) { return '<span class="chip tag">' + h(x) + "</span>"; }).join("");
        var setup = '<section class="card sum"><h3>Setup</h3><p>' + h(who || "Agent") +
          (c.agent_timeout_s ? ", " + dur(c.agent_timeout_s) + " agent time limit" : "") + (c.seed != null ? ", seed " + h(c.seed) : "") + ".</p>" +
          (c.task_path ? '<p class="muted">Task <code>' + h(c.task_path) + "</code></p>" : "") +
          (chips ? '<p class="chips">' + chips + "</p>" : "") +
          (c.sandbox ? '<p class="muted">Sandbox: ' + h(c.sandbox) + "</p>" : "") +
          '<p class="dls">' + dl("config", "Download config.json") + "</p></section>";
        return '<div class="sums">' + result + setup + "</div>";
      }
      function files() {
        var rows = (d.files || []).map(function (f) {
          var link = !f[2] ? '<span class="np">not published</span>'
            : f[2] === "#result" ? dl("result", "download") : f[2] === "#config" ? dl("config", "download")
            : f[2].charAt(0) === "#" ? '<a href="' + f[2] + '" data-view="' + f[2].slice(1) + '">view</a>'
            : '<a href="' + h(f[2]) + '" download>' + (f[0] === "agent/trajectory.json" ? "download trial data" : "download (re-encoded)") + "</a>";
          return '<tr><td class="mono">' + h(f[0]) + '</td><td class="sz">' + kfmt(f[1]) + "B</td><td>" + link + "</td></tr>";
        }).join("");
        return summary() + '<h2 class="lab">Trial folder</h2><div class="scroll"><table class="list files"><thead><tr><th>File</th><th class="n">Size</th><th></th></tr></thead><tbody>' + rows + "</tbody></table></div>" +
          '<p class="muted small">Raw agent logs, the robot request trace and server logs are not published; the Trajectory tab is built from them. Workspace paths read <code>&lt;workspace&gt;</code>.</p>';
      }
      panel.addEventListener("click", function (e) {
        var g = e.target.closest("[data-dl]");
        if (g) {
          e.preventDefault();
          var key = g.getAttribute("data-dl"), text = key === "result" ? d.result_json : d.config_json;
          var url = URL.createObjectURL(new Blob([text || ""], {type: "application/json"})), x = document.createElement("a");
          x.href = url; x.download = d.id + "." + key + ".json"; document.body.appendChild(x); x.click(); x.remove();
          setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
          return;
        }
        var a = e.target.closest("[data-view]"); if (!a) return;
        var k = a.getAttribute("data-view");
        if (k === "filmstrip" || k === "verdict") { e.preventDefault(); history.replaceState(null, "", "#" + (k === "verdict" ? "verdict" : "recording")); show(k === "verdict" ? "verdict" : "recording"); if (k === "filmstrip") { var fs = $("#filmstrip"); if (fs) fs.scrollIntoView(); } }
      });
      show(location.hash.slice(1) || "recording");
    }).catch(function (err) { panel.innerHTML = '<p class="muted">Could not load this trial’s data (' + h(err.message) + ").</p>"; });
  }

  /* ---------------------------------------------------------------- compare */
  function initCompare(root) {
    var p = new URLSearchParams(location.search), a = p.get("a"), b = p.get("b");
    getJSON("/runs/d/trials.json").then(function (idx) {
      var T = idx.trials, byTask = {};
      Object.keys(T).forEach(function (id) { (byTask[T[id][0]] = byTask[T[id][0]] || []).push(id); });
      function label(id) { var t = T[id]; return idx.hm[t[1]][0] + " · " + (STATUS[t[2]] || t[2]) + (t[3] ? "" : " (not counted)"); }
      function sorted(ids) { return ids.slice().sort(function (x, y) { return (T[y][3] - T[x][3]) || (T[x][1] - T[y][1]) || (x < y ? -1 : 1); }); }
      var task = a && T[a] ? T[a][0] : b && T[b] ? T[b][0] : null;
      var tasks = Object.keys(byTask).sort();
      var picker = '<div class="cpick"><label class="frow"><span class="state">Task</span> <select data-task><option value="">Choose a task…</option>' +
        tasks.map(function (k) { return '<option value="' + h(k) + '"' + (k === task ? " selected" : "") + ">" + h(k) + " — " + h(idx.titles[k] || "") + "</option>"; }).join("") + "</select></label>" +
        (task ? '<a class="state" href="/runs/task/' + h(task) + '/">task page</a>' : "") + "</div>";
      if (!task) { root.innerHTML = picker; bindPick(); return; }
      var ids = sorted(byTask[task]);
      if (!a || !T[a]) a = ids.find(function (x) { return x !== b; });
      if (!b || !T[b] || b === a) b = ids.find(function (x) { return x !== a && T[x][1] !== T[a][1] && T[x][3]; }) || ids.find(function (x) { return x !== a; });
      root.innerHTML = picker + (b ? '<p class="ctl"><button type="button" data-both>Play both from the start</button><span class="muted small">Each column follows its own video; click a step to seek.</span></p>' : '<p class="muted">This task has only one trial.</p>') +
        '<div class="cmpgrid"><div class="col" data-side="a"></div><div class="col" data-side="b"></div></div>';
      bindPick();
      [["a", a], ["b", b]].forEach(function (sd) { if (sd[1]) column(sd[0], sd[1], ids); });
      var both = $("[data-both]", root);
      if (both) both.addEventListener("click", function () { $$("video", root).forEach(function (v) { v.currentTime = 0; v.playbackRate = 0.5; v.play(); }); });
      function bindPick() {
        var s = $("[data-task]", root);
        s.addEventListener("change", function () { if (!s.value) return; var l = sorted(byTask[s.value]); location.search = "?a=" + encodeURIComponent(l[0]) + (l[1] ? "&b=" + encodeURIComponent(l.find(function (x) { return x !== l[0] && T[x][1] !== T[l[0]][1]; }) || l[1]) : ""); });
      }
      function column(side, id, ids) {
        var el = $('[data-side="' + side + '"]', root);
        el.innerHTML = '<select aria-label="trial ' + side + '">' + ids.map(function (x) { return '<option value="' + h(x) + '"' + (x === id ? " selected" : "") + ">" + h(label(x)) + "</option>"; }).join("") + '</select><p class="muted small">Loading…</p>';
        $("select", el).addEventListener("change", function (e) { var q = new URLSearchParams(location.search); q.set(side, e.target.value); location.search = "?" + q.toString(); });
        getJSON("/runs/d/" + id + ".json").then(function (d) {
          var st = d.status, vd = d.verdict;
          var html = (d.video ? '<video src="' + h(d.video) + '" controls muted playsinline preload="auto"></video>' : '<div class="novideo">No recording.</div>') +
            '<p class="who"><span class="badge ' + st + '">' + STATUS[st] + '</span><a href="/runs/t/' + h(id) + '/">' + h(idx.hm[d.hm][0]) + "</a></p>" +
            '<dl class="facts"><div><dt>Reward</dt><dd>' + h(d.reward == null ? "–" : d.reward) + '</dd></div><div><dt>Outcome</dt><dd class="mono">' + h(d.outcome || "–") + "</dd></div><div><dt>Env steps</dt><dd>" + num(d.steps_used) + " / " + num(d.max_steps) +
            "</dd></div><div><dt>Requests</dt><dd>" + num(d.requests) + "</dd></div><div><dt>Wall</dt><dd>" + dur(d.wall) + "</dd></div></dl>" +
            (d.withheld ? '<p class="withheld">Trajectory withheld: the agent looked at files outside its workspace.</p>' : (vd.claim_text ? '<p class="small"><span class="muted">' + ({done: "robo done", give_up: "robo give-up", runner: "closed by the runner"}[vd.claim] || "last message") + ": </span>" + h(vd.claim_text.replace(/^\[runner\]\s*/, "").slice(0, 400)) + "</p>" : "") + '<ol class="slist">' + stepListHTML(d) + "</ol>");
          el.innerHTML = $("select", el).outerHTML + html;
          $("select", el).addEventListener("change", function (e) { var q = new URLSearchParams(location.search); q.set(side, e.target.value); location.search = "?" + q.toString(); });
          var v = $("video", el);
          if (!v) return;
          v.playbackRate = 0.5;
          var sy = syncVideo(v, d, function (i) {
            $$(".cur", el).forEach(function (x) { x.classList.remove("cur"); });
            var li = i == null ? null : $('.slist li[data-i="' + i + '"]', el);
            if (li) { li.classList.add("cur"); var box = li.parentNode, top = li.offsetTop - box.offsetTop; if (top < box.scrollTop || top > box.scrollTop + box.clientHeight - 40) box.scrollTop = top - box.clientHeight / 3; }
          });
          el.addEventListener("click", function (e) { var li = e.target.closest("[data-t0]"); if (li) { sy.pin(li.getAttribute("data-i")); seekTo(v, li.getAttribute("data-t0")); } });
        }).catch(function () { el.lastChild.textContent = "Could not load this trial."; });
      }
    });
  }

  /* ---------------------------------------------------------------- task page: pick two trials to compare */
  function initCompareTicks() {
    var boxes = $$("[data-cmp]"), go = $("[data-cmp-go]");
    if (!boxes.length || !go) return;
    function upd() {
      var on = boxes.filter(function (b) { return b.checked; });
      go.disabled = on.length !== 2;
      boxes.forEach(function (b) { b.disabled = !b.checked && on.length >= 2; });
    }
    boxes.forEach(function (b) { b.addEventListener("change", upd); });
    go.addEventListener("click", function () {
      var on = boxes.filter(function (b) { return b.checked; }).map(function (b) { return b.getAttribute("data-cmp"); });
      if (on.length === 2) location.href = "/runs/compare/?a=" + encodeURIComponent(on[0]) + "&b=" + encodeURIComponent(on[1]);
    });
    upd();
  }

  var tbl = $("[data-tasks]"); if (tbl) initTasks(tbl);
  if (document.body.getAttribute("data-trial")) initTrial(document.body.getAttribute("data-trial"));
  var cmp = $("#compare"); if (cmp) initCompare(cmp);
  initCompareTicks();
})();
