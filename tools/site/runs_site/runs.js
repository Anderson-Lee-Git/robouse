/* robouse.ai/runs viewer: sortable, filterable, paged lists (tasks, trials, jobs), the trial page (recording synced to
   the steps, filmstrip, trajectory, verdict, timing and tokens, and the trial folder as the shared file tree) and the
   compare view. No dependencies beyond the site's shared /ui.js (listboxes), /modelset.js (the model comparison set)
   and /filetree.js; data comes from /runs/d/<trial>.json. */
(function () {
  "use strict";
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return [].slice.call((r || document).querySelectorAll(s)); };
  function h(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]; }); }
  function t2(x) { x = Math.round((+x || 0) * 10) / 10; var m = Math.floor(x / 60), s = (x - m * 60).toFixed(1); return m + ":" + (+s < 10 ? "0" : "") + s; }  // round first, then pad: 9.96 -> 0:10.0
  function play(v) { var p = v.play(); if (p && p.catch) p.catch(function () {}); }  // a pause right after play rejects; that is not an error
  function dur(x) { if (x == null) return "–"; x = +x; return x < 120 ? x.toFixed(x < 10 ? 1 : 0) + " s" : (x / 60).toFixed(1) + " min"; }
  function rew(x) { return x == null || isNaN(+x) ? "–" : (+x).toFixed(1); }
  function mfirst(l) { var i = String(l).indexOf(" + "); return i < 0 ? l : l.slice(i + 3) + " · " + l.slice(0, i); }  // "Claude Code + Opus 5.5" -> "Opus 5.5 · Claude Code"
  function num(x) { return x == null ? "–" : Number(x).toLocaleString("en-US"); }
  function kfmt(x) { x = +x || 0; return x >= 1e6 ? (x / 1e6).toFixed(2) + "M" : x >= 1e4 ? Math.round(x / 1e3) + "k" : x >= 1e3 ? (x / 1e3).toFixed(1) + "k" : String(x); }
  function getJSON(u) { return fetch(u).then(function (r) { if (!r.ok) throw new Error(r.status + " " + u); return r.json(); }); }
  var coll = typeof Intl !== "undefined" ? new Intl.Collator(undefined, {numeric: true, sensitivity: "base"}) : null;
  function cmpText(a, b) { return coll ? coll.compare(a, b) : (a < b ? -1 : a > b ? 1 : 0); }
  var STATUS = {ok: "Solved", no: "Not solved", infra: "Infra failure", partial: "Partial"};
  var reduce = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
  function setKeys() { return window.ModelSet && ModelSet.keys && ModelSet.pairs && ModelSet.pairs().length ? ModelSet.keys() : null; }
  function emptyState(title, text, extra) { return '<div class="empty-state"><b>' + h(title) + "</b>" + h(text) + (extra || "") + "</div>"; }

  /* ---------------------------------------------------------------- tooltip (charts) */
  var tip;
  function showTip(e, text) {
    if (!tip) { tip = document.createElement("div"); tip.className = "tip"; tip.setAttribute("role", "tooltip"); document.body.appendChild(tip); }
    tip.textContent = text; tip.style.display = "block";
    var x = Math.min(e.clientX + 12, window.innerWidth - tip.offsetWidth - 8), y = e.clientY + 14;
    if (y + tip.offsetHeight > window.innerHeight - 8) y = e.clientY - tip.offsetHeight - 10;
    tip.style.left = Math.max(8, x) + "px"; tip.style.top = y + "px";
  }
  function hideTip() { if (tip) tip.style.display = "none"; }
  document.addEventListener("mousemove", function (e) {
    var el = e.target.closest && e.target.closest("[data-tip]");
    if (el) showTip(e, el.getAttribute("data-tip")); else hideTip();
  });
  window.addEventListener("scroll", hideTip, {passive: true});

  /* ---------------------------------------------------------------- wide tables: a sticky header when the table fits,
     its own horizontal scroll (with a sticky first column) when it does not */
  function fit() {
    $$(".scroll.tbl, .scroll.mx").forEach(function (s) {
      var t = s.querySelector("table"); if (!t) return;
      s.classList.remove("fits");
      s.classList.toggle("fits", t.scrollWidth <= s.clientWidth + 1);
    });
  }
  var fitT = 0;
  window.addEventListener("resize", function () { clearTimeout(fitT); fitT = setTimeout(fit, 80); });

  /* ---------------------------------------------------------------- lists: filter, sort, page */
  function initList(root, hook) {
    hook = hook || {};
    var table = $("table", root); if (!table) return null;
    var tb = table.tBodies[0], rows = [].slice.call(tb.rows);
    var limit0 = +root.getAttribute("data-limit") || Infinity, limit = limit0;
    var noun = root.getAttribute("data-noun") || "rows";
    var P = new URLSearchParams(location.search);
    var fsel = $$("[data-lf]", root), q = $("[data-lq]", root), scope = $("[data-lscope]", root);
    var more = $("[data-lmore]", root), moreBox = more && more.parentNode, empty = $("[data-lempty]", root), count = $("[data-lcount]", root);
    var wrap = table.closest(".scroll") || table;
    var hasPairs = rows.some(function (r) { return r.hasAttribute("data-pair"); });
    var only = hook.noOnly || !hasPairs ? null : P.get("m");
    fsel.forEach(function (s) { var k = s.getAttribute("data-lf"); if (P.get(k)) s.value = P.get(k); s.addEventListener("change", reset); });
    function qsync() { if (q && window.UI && UI.searchSync) UI.searchSync(q); }
    if (q) { q.value = P.get("q") || ""; q.addEventListener("input", reset); qsync(); }
    if (scope) { if (P.get("scope") === "all" || only) scope.value = "all"; scope.addEventListener("change", reset); }
    var pill = null;
    if (only) {
      var r0 = rows.filter(function (r) { return r.getAttribute("data-pair") === only; })[0];
      var lab = r0 ? ($("th a", r0) || r0).textContent : only;
      pill = document.createElement("button");
      pill.type = "button"; pill.className = "fpill"; pill.setAttribute("aria-label", "Showing only " + lab + ". Remove this filter");
      pill.innerHTML = "<span>Only " + h(lab) + '</span><i aria-hidden="true">×</i>';
      var frow = $(".frow", root); if (frow) frow.insertBefore(pill, frow.firstChild);
      pill.addEventListener("click", function () { only = null; pill.remove(); pill = null; reset(); });
    }
    function match(r) {
      for (var i = 0; i < fsel.length; i++) {
        var v = fsel[i].value; if (!v) continue;
        var a = r.getAttribute("data-" + fsel[i].getAttribute("data-lf"));
        if (a == null || a.split(" ").indexOf(v) < 0) return false;
      }
      if (q && q.value.trim()) {
        var d = r.getAttribute("data-q") || r.textContent.toLowerCase();
        if (!q.value.trim().toLowerCase().split(/\s+/).every(function (w) { return d.indexOf(w) >= 0; })) return false;
      }
      var pr = r.getAttribute("data-pair");
      if (only && pr && pr !== only) return false;
      if (scope && scope.value === "set" && pr) { var ks = setKeys(); if (ks && ks.indexOf(pr) < 0) return false; }
      if (r.hasAttribute("data-m") && r.classList.contains("ms-off")) return false;
      return hook.match ? hook.match(r) : true;
    }
    function fmt(n) { return Number(n).toLocaleString("en-US"); }
    function apply() {
      var n = 0;
      rows.forEach(function (r) { var ok = match(r); if (ok) n++; r.hidden = !ok || n > limit; });
      if (count) count.textContent = (n === rows.length ? fmt(rows.length) : fmt(n) + " of " + fmt(rows.length)) + " " + noun;
      if (moreBox) { moreBox.hidden = n <= limit; more.textContent = "Show all " + fmt(n) + " " + noun; }
      if (empty) { empty.hidden = n > 0; wrap.hidden = n === 0; }
      if (!hook.noUrl) {
        var p = new URLSearchParams(location.search);
        fsel.forEach(function (s) { var k = s.getAttribute("data-lf"); if (s.value) p.set(k, s.value); else p.delete(k); });
        if (q) { if (q.value.trim()) p.set("q", q.value.trim()); else p.delete("q"); }
        if (scope) { if (scope.value === "all" && !only) p.set("scope", "all"); else p.delete("scope"); }
        if (hasPairs && !hook.noOnly) { if (only) p.set("m", only); else p.delete("m"); }
        if (hook.write) hook.write(p);
        var qs = p.toString();
        history.replaceState(null, "", location.pathname + (qs ? "?" + qs : "") + location.hash);
      }
      if (hook.after) hook.after();
      fit();
    }
    function reset() { limit = limit0; apply(); }
    if (more) more.addEventListener("click", function () {
      var first = rows.filter(function (r) { return !r.hidden; }).length;
      limit = Infinity; apply();
      var next = rows.filter(function (r) { return !r.hidden; })[first], a = next && $("a, input", next);
      if (a) a.focus({preventScroll: true});
    });
    var clear = $("[data-lclear]", root);
    if (clear) clear.addEventListener("click", function () {
      fsel.forEach(function (s) { s.value = ""; });
      if (q) { q.value = ""; qsync(); }
      if (scope) scope.value = "set";
      only = null; if (pill) { pill.remove(); pill = null; }
      if (hook.clear) hook.clear();
      reset();
    });
    /* sorting: every th[data-sort] carries a button; missing values stay last in both directions */
    var ths = $$("thead th[data-sort]", table);
    function val(c, isNum) {
      if (!c) return null;
      var el = c.hasAttribute("data-v") ? c : c.querySelector("[data-v]");
      var s = el ? el.getAttribute("data-v") : c.textContent.trim();
      if (isNum) { var x = parseFloat(s); return isNaN(x) || x === -1 ? null : x; }
      return s && s !== "–" ? s.toLowerCase() : null;
    }
    ths.forEach(function (th) {
      var b = $("button.sb", th); if (!b) return;
      b.addEventListener("click", function () {
        var idx = [].indexOf.call(th.parentNode.children, th), isNum = th.getAttribute("data-sort") === "num";
        var cur = th.getAttribute("aria-sort"), dir = cur === "none" ? (isNum ? "descending" : "ascending") : cur === "descending" ? "ascending" : "descending";
        ths.forEach(function (x) { x.setAttribute("aria-sort", "none"); });
        th.setAttribute("aria-sort", dir);
        var sg = dir === "ascending" ? 1 : -1;
        var keyed = rows.map(function (r, i) { return {r: r, v: val(r.children[idx], isNum), i: i}; });
        keyed.sort(function (a, b) {
          if (a.v === null || b.v === null) return a.v === b.v ? a.i - b.i : a.v === null ? 1 : -1;
          var d = isNum ? a.v - b.v : cmpText(a.v, b.v);
          return d ? d * sg : a.i - b.i;
        });
        rows = keyed.map(function (k) { return k.r; });
        var frag = document.createDocumentFragment();
        rows.forEach(function (r) { frag.appendChild(r); });
        tb.appendChild(frag);
        apply();
      });
    });
    document.addEventListener("modelset", apply);
    apply();
    return {apply: apply, reset: reset};
  }

  /* ---------------------------------------------------------------- tasks table (index and suite pages) */
  function initTasks(root) {
    var table = $("table", root), P = new URLSearchParams(location.search);
    var st = {suite: P.get("s") || "", model: P.get("m") || "", outcome: P.get("o") || ""};
    var mSel = $('[data-lx="model"]', root), oSel = $('[data-lx="outcome"]', root), pills = $$(".pill[data-suite]", root);
    if (mSel) mSel.value = st.model;
    if (oSel) oSel.value = st.outcome;
    var heads = $$("thead th", table), colIndex = {};
    heads.forEach(function (th, i) { if (th.getAttribute("data-col")) colIndex[th.getAttribute("data-col")] = i; });
    function parse(r) {
      var m = {};
      r.getAttribute("data-st").split(" ").forEach(function (p) { var i = p.lastIndexOf(":"); m[p.slice(0, i)] = p.slice(i + 1); });
      return m;
    }
    var list = initList(root, {
      noOnly: true,
      match: function (r) {
        if (st.suite && r.getAttribute("data-suite") !== st.suite) return false;
        if (!st.outcome) return true;
        var m = r._st || (r._st = parse(r));
        if (st.model && st.outcome !== "split") return m[st.model] === st.outcome;
        var ks = setKeys(), keys = Object.keys(m).filter(function (k) { return !ks || ks.indexOf(k) >= 0 || k === st.model; });
        var vals = keys.map(function (k) { return m[k]; });
        if (st.outcome === "split") return vals.some(function (v) { return v === "ok" || v === "some"; }) && vals.some(function (v) { return v === "no" || v === "some"; });
        return vals.indexOf(st.outcome) >= 0;
      },
      write: function (p) {
        [["s", st.suite], ["m", st.model], ["o", st.outcome]].forEach(function (kv) { if (kv[1]) p.set(kv[0], kv[1]); else p.delete(kv[0]); });
      },
      clear: function () { st = {suite: "", model: "", outcome: ""}; if (mSel) mSel.value = ""; if (oSel) oSel.value = ""; },
      after: function () {
        pills.forEach(function (b) { b.setAttribute("aria-pressed", b.getAttribute("data-suite") === st.suite ? "true" : "false"); });
        $$(".hl", table).forEach(function (c) { c.classList.remove("hl"); });
        var ci = st.model ? colIndex[st.model] : -1;
        if (ci >= 0) {
          heads[ci].classList.add("hl");
          $$("tbody tr", table).forEach(function (r) { var c = r.children[ci]; if (c) c.classList.add("hl"); });
        }
      }
    });
    pills.forEach(function (b) { b.addEventListener("click", function () { st.suite = b.getAttribute("data-suite"); list.reset(); }); });
    if (mSel) mSel.addEventListener("change", function () { st.model = mSel.value; list.reset(); });
    if (oSel) oSel.addEventListener("change", function () { st.outcome = oSel.value; list.reset(); });
  }

  /* the matrix: an empty state when the comparison set is empty */
  function initMatrix(mx) {
    var emp = mx.parentNode.querySelector(".mx-empty");
    document.addEventListener("modelset", function (e) {
      var none = !e.detail.keys.length;
      mx.hidden = none; if (emp) emp.hidden = !none;
      fit();
    });
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
    size = size || sp.disp || sp.tile;
    var k = size / sp.tile, cols = Math.min(sp.n, sp.cols), rows = Math.ceil(sp.n / sp.cols);
    return "background-image:url(" + sp.src + ");background-size:" + (cols * sp.tile * k) + "px " + (rows * sp.tile * k) + "px;background-position:-" +
      ((i % sp.cols) * sp.tile * k) + "px -" + (Math.floor(i / sp.cols) * sp.tile * k) + "px";
  }
  function stepListHTML(d) {
    return d.steps.map(function (s) {
      var a = actionOf(s), v = s.v;
      var x = s.env && s.env[1] > s.env[0] ? "+" + (s.env[1] - s.env[0]) + " steps" : "";
      return '<li data-i="' + s.i + '"' + (v ? ' data-t0="' + v[0] + '" tabindex="0" aria-label="Step ' + s.i + ", " + h(a.text.slice(0, 120)) + ", seek to " + t2(v[0]) + '"' : ' class="nov"') +
        '><span class="i">' + s.i + '</span><span class="t">' + (v ? t2(v[0]) : "") +
        '</span><span class="a ' + a.cls + '" title="' + h(a.text.slice(0, 400)) + '">' + h(a.text.slice(0, 220)) + '</span><span class="x' + (exitOf(s) ? " err" : "") + '">' + (exitOf(s) ? "exit≠0" : x) + "</span></li>";
    }).join("");
  }
  function keyActivate(box) {  // Enter or space on a focusable step row seeks, like a click
    box.addEventListener("keydown", function (e) {
      if ((e.key === "Enter" || e.key === " ") && e.target.matches && e.target.matches("li[data-t0]")) { e.preventDefault(); e.stopPropagation(); e.target.click(); }
    });
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
  function scrollInto(li) {
    if (!li) return;
    var box = li.parentNode, top = li.offsetTop - box.offsetTop;
    if (top < box.scrollTop || top > box.scrollTop + box.clientHeight - 40) box.scrollTop = top - box.clientHeight / 3;
  }
  /* shortcuts never fire while the reader types, picks from a list, or works in the file tree */
  function busyTarget(e) {
    var t = e.target || {};
    if (e.metaKey || e.ctrlKey || e.altKey) return true;
    if (/^(INPUT|SELECT|TEXTAREA)$/.test(t.tagName || "") || t.isContentEditable) return true;
    return !!(t.closest && t.closest(".ft, .lb, .lb-pop, .ms-pop, [role=tab], [role=listbox], [role=dialog]"));
  }

  var WITHHELD = "Trajectory not published: during this trial the agent looked at files outside its workspace (for example listing the home folder or searching the whole disk), so its commands and their outputs may show unrelated local files. The recording, the camera images, the reward and the outcome are shown.";

  /* ---------------------------------------------------------------- trial page */
  function initTrial(id) {
    var stage = $("#stage"), panel = $("#panel"), player = $("#player"), v = $("#vid"), pctl = $(".pctl", player);
    var below = document.createElement("div"); below.id = "below"; stage.parentNode.insertBefore(below, stage.nextSibling);
    var tabs = $$("nav.tabs [role=tab]");
    function tabOf(hash) { var t = (hash || "").replace(/^#/, "").split("/")[0]; return /^(recording|trajectory|verdict|run|files)$/.test(t) ? t : "recording"; }
    stage.className = "stage t-" + tabOf(location.hash);
    tabs.forEach(function (a) { a.setAttribute("aria-selected", a.getAttribute("data-tab") === tabOf(location.hash) ? "true" : "false"); a.tabIndex = a.getAttribute("aria-selected") === "true" ? 0 : -1; });
    getJSON("/runs/d/" + id + ".json").then(function (d) {
      var current = null, sync = null;
      var SPEEDS = [0.25, 0.5, 1];
      var speed = +(localStorage.getItem("runs-speed") || 0.5);
      if (SPEEDS.indexOf(speed) < 0) speed = 0.5;
      if (v && pctl) {
        v.playbackRate = speed;
        v.addEventListener("loadedmetadata", function () { v.playbackRate = speed; });
        var laneEl = $(".lane", pctl), knob = $(".lane b", pctl), now = $(".now", pctl), playB = $('[data-k="play"]', pctl);
        $(".lane-mk", pctl).innerHTML = d.steps.filter(function (s) { return s.v && s.robo; }).map(function (s) {
          return '<i style="left:' + pct(s.v[0]) + '%"' + (hasImg(s) ? ' class="im"' : "") + "></i>";
        }).join("");
        $$("button", pctl).forEach(function (b) { b.disabled = false; });
        if (!d.steps.some(function (s) { return s.v; })) $$('[data-k="prev"], [data-k="next"]', pctl).forEach(function (b) { b.disabled = true; });
        $$("[data-speed]", pctl).forEach(function (x) { x.setAttribute("aria-pressed", +x.getAttribute("data-speed") === speed ? "true" : "false"); });
        v.addEventListener("timeupdate", function () { var p = pct(v.currentTime); knob.style.left = p + "%"; laneEl.setAttribute("aria-valuenow", Math.round(p)); laneEl.setAttribute("aria-valuetext", t2(v.currentTime)); });
        var setPlay = function () { var on = !v.paused; playB.classList.toggle("on", on); playB.setAttribute("aria-label", on ? "Pause" : "Play"); };
        v.addEventListener("play", setPlay); v.addEventListener("pause", setPlay); v.addEventListener("ended", setPlay);
        laneEl.addEventListener("click", function (e) { var r = laneEl.getBoundingClientRect(); seekTo(v, (e.clientX - r.left) / r.width * dur0()); });
        laneEl.addEventListener("keydown", function (e) {
          if (e.key === "Home") { seekTo(v, 0); e.preventDefault(); }
          else if (e.key === "End") { seekTo(v, dur0()); e.preventDefault(); }
          else if (e.key === "PageUp" || e.key === "PageDown") { seekTo(v, v.currentTime + (e.key === "PageUp" ? -5 : 5)); e.preventDefault(); }
        });
        pctl.addEventListener("click", function (e) {
          var b = e.target.closest("button"); if (!b || b.disabled) return;
          if (b.hasAttribute("data-speed")) {
            speed = +b.getAttribute("data-speed"); v.playbackRate = speed; try { localStorage.setItem("runs-speed", speed); } catch (err) {}
            $$("[data-speed]", pctl).forEach(function (x) { x.setAttribute("aria-pressed", x === b ? "true" : "false"); });
          } else if (b.getAttribute("data-k") === "play") { if (v.paused) play(v); else v.pause(); }
          else if (b.getAttribute("data-k") === "full") fullscreen();
          else step(b.getAttribute("data-k") === "next" ? 1 : -1);
        });
        sync = syncVideo(v, d, function (i) {
          $$(".cur[data-i]").forEach(function (el) { el.classList.remove("cur"); });
          if (i == null) { now.textContent = ""; return; }
          $$('[data-i="' + i + '"]').forEach(function (el) { el.classList.add("cur"); });
          var s = d.steps.find(function (x) { return x.i === i; });
          now.textContent = "Step " + i + (s ? " · " + actionOf(s).text.slice(0, 80) : "");
          scrollInto($('.slist li[data-i="' + i + '"]'));
          markTiles(i);
        });
        document.addEventListener("keydown", function (e) {
          if (busyTarget(e) || current === "files") return;
          var tag = (e.target || {}).tagName || "";
          if (e.key === "ArrowRight") { step(1); e.preventDefault(); }
          else if (e.key === "ArrowLeft") { step(-1); e.preventDefault(); }
          else if (e.key === " " && !/^(BUTTON|A|SUMMARY|VIDEO)$/.test(tag)) { if (v.paused) play(v); else v.pause(); e.preventDefault(); }
          else if (e.key === "f" || e.key === "F") { fullscreen(); e.preventDefault(); }
        });
      }
      function fullscreen() {
        if (!v) return;
        if (document.fullscreenElement) { document.exitFullscreen(); return; }
        if (v.requestFullscreen) v.requestFullscreen(); else if (v.webkitEnterFullscreen) v.webkitEnterFullscreen();
      }
      if (v) v.addEventListener("click", function () { if (v.paused) play(v); else v.pause(); });
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
        $$(".tile[data-s]").forEach(function (t) { var s = +t.getAttribute("data-s"); if (s <= i && (best == null || s >= +best.getAttribute("data-s"))) best = t; t.classList.remove("cur"); t.removeAttribute("aria-current"); });
        if (best) { best.classList.add("cur"); best.setAttribute("aria-current", "true"); }
      }
      document.addEventListener("click", function (e) {
        var el = e.target.closest && e.target.closest("[data-t0], [data-seek]");
        if (!el || !v || !panel.contains(el) && !below.contains(el)) return;
        if (e.target.closest("a, summary, pre, details .txt")) return;
        var pin = el.getAttribute("data-i") || el.getAttribute("data-s") || (el.closest("[data-i]") || {getAttribute: function () { return null; }}).getAttribute("data-i");
        if (sync) sync.pin(pin);
        if (el.classList.contains("tile") && !(sync && sync.marks.length)) { $$(".tile.cur").forEach(function (t) { t.classList.remove("cur"); }); el.classList.add("cur"); }
        seekTo(v, el.getAttribute("data-seek") || el.getAttribute("data-t0"));
        var vr = v.getBoundingClientRect();  /* phones: a seek from below brings the video back into view */
        if (vr.bottom < 48 || vr.top > innerHeight - 48) v.scrollIntoView({block: "nearest", behavior: reduce ? "auto" : "smooth"});
      });
      keyActivate(panel);

      function show(tab, focusTab) {
        tab = tabOf(tab);
        if (tab === current && tab !== "files") return;
        current = tab;
        tabs.forEach(function (a) { var on = a.getAttribute("data-tab") === tab; a.setAttribute("aria-selected", on ? "true" : "false"); a.tabIndex = on ? 0 : -1; if (on && focusTab) a.focus(); });
        stage.className = "stage t-" + tab;
        if (v && (tab === "run" || tab === "files")) v.pause();
        below.innerHTML = "";
        panel.innerHTML = ({recording: recording, trajectory: trajectory, verdict: verdict, run: run, files: files})[tab]();
        panel.setAttribute("aria-busy", "false");
        if (tab === "recording" && d.sprite) below.innerHTML = strip();
        if (tab === "run") bindRun();
        if (tab === "files") mountFiles();
        if (sync) { var i = sync.now(); if (i != null) { $$('[data-i="' + i + '"]').forEach(function (el) { el.classList.add("cur"); }); markTiles(i); } }
      }
      tabs.forEach(function (a) {
        a.addEventListener("click", function (e) { e.preventDefault(); history.replaceState(null, "", "#" + a.getAttribute("data-tab")); show(a.getAttribute("data-tab")); });
      });
      var tl = $("nav.tabs");
      tl.addEventListener("keydown", function (e) {
        var k = tabs.indexOf(document.activeElement); if (k < 0) return;
        var n = e.key === "ArrowRight" ? k + 1 : e.key === "ArrowLeft" ? k - 1 : e.key === "Home" ? 0 : e.key === "End" ? tabs.length - 1 : null;
        if (n == null) return;
        e.preventDefault();
        n = (n + tabs.length) % tabs.length;
        history.replaceState(null, "", "#" + tabs[n].getAttribute("data-tab"));
        show(tabs[n].getAttribute("data-tab"), true);
      });
      window.addEventListener("hashchange", function () { show(location.hash.slice(1)); });

      function withheldNote() { return '<div class="withheld" role="note"><b>Trajectory withheld</b><p>' + h(WITHHELD.replace(/^Trajectory not published: d/, "D")) + "</p></div>"; }
      function recording() {
        if (d.withheld) return withheldNote();
        if (!d.steps.length) return emptyState("No trajectory was recorded for this trial.", "The recording and the Verdict tab still show what happened.");
        var n = d.steps.length;  /* the same count as the Trajectory tab: every step listed */
        var first = d.steps[0] && d.steps[0].i > 1 && d.prompt ? '<li class="nov"><span class="i">1</span><span class="t"></span><span class="a msg"><a href="#trajectory">Task prompt</a></span><span class="x"></span></li>' : "";
        return '<div class="recbox"><div class="rechead"><span>Steps · click one to seek</span><span class="num">' + n + ' steps<span class="keys"> · <kbd>←</kbd> <kbd>→</kbd> to step</span></span></div><ol class="slist">' + first + stepListHTML(d) + "</ol>" +
          (d.hidden ? '<p class="muted small slnote">' + d.hidden + " one-action steps in the middle are not listed.</p>" : "") + "</div>";
      }
      function strip() {
        var sp = d.sprite;
        return '<section class="strip" id="filmstrip" aria-label="Camera images"><div class="rechead"><span>Camera images the agent looked at</span><span class="num">' +
          (sp.total > sp.n ? sp.n + " of " + sp.total + " shown" : sp.total) + '</span></div><div class="tiles" data-fade>' +
          d.obs.map(function (o) {
            var lab = o[1] != null ? "step " + o[1] : o[0].replace(/\.png$/, "");
            return '<button type="button" class="tile"' + (o[1] != null ? ' data-s="' + o[1] + '"' : "") + (o[3] != null ? ' data-seek="' + o[3] + '"' : "") + ' title="' + h(o[0]) + '" aria-label="Camera image ' + h(lab) + (o[3] != null ? ", seek the recording here" : "") + '"><i style="' + sprStyle(sp, o[2]) + '"></i><span>' + h(lab) + "</span></button>";
          }).join("") + "</div></section>";
      }
      function trajectory() {
        var out = [];
        if (d.prompt) out.push('<details class="disc prompt"><summary>Task prompt</summary><div class="txt">' + h(d.prompt) + "</div></details>");
        if (d.withheld) return out.join("") + withheldNote();
        if (!d.steps.length) return out.join("") + emptyState("No trajectory was recorded for this trial.", "The harness wrote no steps; the Verdict tab shows how the episode ended.");
        out.push('<ol class="traj">');
        var prev = null;
        d.steps.forEach(function (s) {
          if (d.hidden && prev != null && s.i - prev > 1) out.push('<li class="gap">… ' + d.hidden + " one-action steps not shown …</li>");
          prev = s.i;
          var head = '<div class="sh"><span class="num">' + s.i + '</span><span class="src">' + ({agent: "Agent", system: "System", user: "Prompt"}[s.src] || h(s.src)) + "</span>" +
            (s.ts != null ? '<span class="num">+' + dur(s.ts) + "</span>" : "") + (s.tk ? '<span class="num" title="prompt / output tokens">' + kfmt(s.tk[0]) + " / " + kfmt(s.tk[1]) + " tok</span>" : "") +
            (s.v ? '<button type="button" class="seek" data-seek="' + s.v[0] + '" title="Seek the recording here">' + t2(s.v[0]) + "</button>" : "") + "</div>";
          var body = "";
          if (s.m) body += '<div class="txt">' + h(s.m) + "</div>";
          if (s.r) body += '<details class="disc rsn"><summary>Reasoning</summary><div class="txt">' + h(s.r) + "</div></details>";
          (s.c || []).forEach(function (c) {
            body += '<pre class="cmd"><code>' + h(c.a) + "</code></pre>";
            if (c.b) body += '<pre class="out"><code>' + h(c.b) + "</code></pre>";
            if (c.img && d.sprite) body += '<div class="imgs">' + c.img.map(function (k) { return '<i style="' + sprStyle(d.sprite, k) + '"></i>'; }).join("") + "</div>";
            if (c.o != null) body += '<details class="disc res"' + (c.n <= 8 ? " open" : "") + "><summary>Output · " + c.n + " line" + (c.n === 1 ? "" : "s") + (c.x != null ? ' · <span class="x-err">exit ' + h(c.x) + "</span>" : "") + '</summary><pre class="out"><code>' + h(c.o) + "</code></pre></details>";
          });
          out.push('<li class="st ' + h(s.src) + '" data-i="' + s.i + '" id="s' + s.i + '">' + head + body + "</li>");
        });
        out.push("</ol>");
        return out.join("");
      }
      /* optional groups from the trial folder (metrics, placement, operator, safety, cost, VLA timing): quiet labelled
         groups, nothing when the data is absent */
      var X = d.extra || {};
      function grp(title, rows, note) {
        rows = rows.filter(function (r) { return r && r[1] != null && r[1] !== ""; });
        if (!rows.length) return "";
        return '<section class="xg"><h3>' + h(title) + '</h3><dl>' + rows.map(function (r) {
          return '<div' + (r[3] ? ' title="' + h(r[3]) + '"' : "") + "><dt>" + h(r[0]) + '</dt><dd><span class="xv">' + h(r[1]) + "</span>" + (r[2] ? ' <span class="xu">' + h(r[2]) + "</span>" : "") + "</dd></div>";
        }).join("") + "</dl>" + (note || "") + "</section>";
      }
      function verdictExtras() {
        var out = "";
        if (X.metrics) out += grp("Episode metrics", X.metrics.map(function (m) { return [m[0], m[1], m[2], m[3] ? "Better: " + m[3] : ""]; }));
        if (X.placement) { var p = X.placement; out += grp("Placement", [["Split", p.split], ["Objects moved", p.objects != null ? String(p.objects) : null], ["Largest offset", p.max_cm != null ? p.max_cm.toFixed(1) : null, "cm"], ["Placement seed", p.seed != null ? String(p.seed) : null]]); }
        if (X.mode) out += grp("Embodiment", [["Mode", X.mode]]);
        if (X.operator) { var o = X.operator; out += grp(o.rubric ? "Operator rubric" : "Operator verdict", [[o.rubric ? "Highest stage" : "Verdict", o.verdict], ["Channel", o.channel]], o.note ? '<p class="xn">' + h(o.note) + "</p>" : ""); }
        if (X.safety) {
          var sf = X.safety, c = sf.counts || {};
          out += grp("Safety events and vetoes", Object.keys(c).map(function (k) { return [k, String(c[k])]; }),
            (sf.items && sf.items.length ? '<ol class="xl">' + sf.items.map(function (e) { return "<li>" + (e[0] != null ? '<span class="num">' + (+e[0]).toFixed(1) + " s</span>" : "<span></span>") + '<span class="mono">' + h(e[1]) + "</span><span>" + h(e[2]) + "</span></li>"; }).join("") + "</ol>" : "") +
            (sf.more ? '<p class="xn">and ' + sf.more + " more</p>" : ""));
        }
        return out ? '<div class="xgs">' + out + "</div>" : "";
      }
      function runExtras() {
        var out = "";
        if (X.cost) { var c = X.cost; out += grp("Cost", [["Prompt tokens", c.prompt != null ? num(c.prompt) : null], ["Cached", c.cached ? num(c.cached) : null], ["Completion tokens", c.completion != null ? num(c.completion) : null], ["Cost", c.usd != null ? "$" + (+c.usd).toFixed(c.usd < 1 ? 4 : 2) : null, "USD"], ["Source", c.source || null]]); }
        if (X.vla) { var v = X.vla; out += grp("Policy inference", [["Inferences", num(v.inferences)], ["Chunk size", v.chunk != null ? String(v.chunk) : null, "actions"], ["Round trip", v.roundtrip ? v.roundtrip[0].toFixed(2) + " · " + v.roundtrip[1].toFixed(2) : null, "s median · p90"], ["Server", v.server ? v.server[0].toFixed(2) + " · " + v.server[1].toFixed(2) : null, "s median · p90"]]); }
        return out ? '<div class="xgs">' + out + "</div>" : "";
      }
      function verdict() {
        var vd = d.verdict, r = d.reward, solved = r != null && r > 0;
        var claim = {done: ["Called robo done", ""], give_up: ["Gave up", "warn"], runner: ["Never called robo done", "warn"], none: ["No robo done or give-up", "warn"]}[vd.claim] || ["–", ""];
        var check = d.status === "partial" ? ["Not scored (partial)", "warn"] : d.status === "infra" ? ["Infrastructure failure", "warn"] : solved ? ["Passed · reward " + rew(r), "ok"] : ["Failed · reward " + rew(r), "no"];
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
          ["Backend · env", [spec.backend, spec.env].filter(Boolean).join(" · ")], ["Observation", spec.observation_mode], ["Camera", spec.camera], ["Skills", spec.skills == null ? null : String(spec.skills)], ["Seed", d.seed != null ? d.seed : spec.seed], ["Safety", spec.safety]];
        return '<div class="vd">' +
          '<section class="card"><h3>Agent said</h3><p class="big ' + claim[1] + '">' + claim[0] + "</p>" +
          (d.withheld ? '<p class="muted small">Withheld with the trajectory.</p>' : said ? '<div class="txt">' + h(said) + "</div>" + (vd.claim_text ? "" : '<p class="muted small">(its last message)</p>') : '<p class="muted small">No message.</p>') + "</section>" +
          '<section class="card"><h3>Simulator checked</h3><p class="big ' + check[1] + '">' + check[0] + '</p><p class="muted small">The claim never counts: the episode server judges the final physical state.</p>' +
          (vd.verifier ? '<pre class="out"><code>' + h(vd.verifier) + "</code></pre>" : "") + (vd.infra && vd.infra.length ? '<pre class="out"><code>' + h(vd.infra.join("\n")) + "</code></pre>" : "") + "</section>" +
          '<p class="rel ' + relc + '">' + h(rel) + "</p>" +
          '<section class="card wide"><h3>Episode</h3><dl class="kv">' + kv.filter(function (x) { return x[1] != null && x[1] !== ""; }).map(function (x) { return "<dt>" + h(x[0]) + "</dt><dd>" + h(x[1]) + "</dd>"; }).join("") + "</dl></section></div>" + verdictExtras();
      }
      function run() {
        var tk = d.tokens, stats = [];
        /* wall time, robot requests and env steps are in the facts above the tabs; this tab adds only what is new */
        stats.push(["Episode", dur(d.ep_wall), ""]);
        stats.push(["Video", d.duration != null ? dur(d.duration) : "–", "robot moving"]);
        stats.push(["Agent steps", num(d.steps.filter(function (s) { return s.src === "agent"; }).length || null), ""]);
        if (d.motion != null) stats.push(["Motion requests", num(d.motion), "of " + num(d.requests)]);
        var html = '<dl class="stats">' + stats.map(function (s) { return "<div><dt>" + s[0] + '</dt><dd class="num">' + s[1] + (s[2] ? "<small>" + s[2] + "</small>" : "") + "</dd></div>"; }).join("");
        if (tk) {
          html += '<div><dt>Input tokens</dt><dd class="num">' + kfmt(tk["in"]) + (tk.cached ? "<small>" + Math.round(100 * tk.cached / Math.max(1, tk["in"])) + "% cached</small>" : "") + "</dd></div>" +
            '<div><dt>Output tokens</dt><dd class="num">' + kfmt(tk.out) + (tk.reasoning ? "<small>" + kfmt(tk.reasoning) + " reasoning</small>" : "") + "</dd></div>" +
            (tk.cost ? '<div><dt>Cost</dt><dd class="num">$' + tk.cost.toFixed(2) + "</dd></div>" : "");
        }
        html += "</dl>" + runExtras();
        if (d.withheld) return html + withheldNote();
        var ts = d.steps.filter(function (s) { return s.ts != null; });
        if (ts.length > 1) {
          var T = ts[ts.length - 1].ts - ts[0].ts || 1;
          var segs = ts.slice(0, -1).map(function (s, k) {
            var dt = Math.max(0, ts[k + 1].ts - s.ts);
            return '<i style="flex:' + Math.max(dt, T / 2000).toFixed(3) + ' 0 0" data-go="' + ts[k + 1].i + '" data-tip="' + dur(dt) + " before step " + ts[k + 1].i + "\n" + h(actionOf(ts[k + 1]).text.slice(0, 120)) + '"></i>';
          });
          html += '<section class="chart"><h3>Wall clock between steps<span>' + dur(T) + " from the first step to the last; each segment is the time before a step (the previous command running, then the model thinking). Click one for the step.</span></h3>" +
            '<div class="tl">' + segs.join("") + '</div><div class="axis num"><span>0</span><span>' + dur(T / 2) + "</span><span>" + dur(T) + "</span></div></section>";
        }
        var tks = d.steps.filter(function (s) { return s.tk; });
        var outSum = tks.reduce(function (a, s) { return a + s.tk[1]; }, 0), outOk = !tk || outSum >= 0.5 * (tk.out || 0);
        if (tks.length > 1) {
          var maxIn = Math.max.apply(null, tks.map(function (s) { return s.tk[0]; })) || 1, maxOut = Math.max.apply(null, tks.map(function (s) { return s.tk[1]; })) || 1;
          html += '<section class="chart"><h3>Input tokens per step<span>the context the model read, up to ' + kfmt(maxIn) + '</span></h3><div class="bars">' +
            tks.map(function (s) { return '<i style="height:' + (100 * s.tk[0] / maxIn).toFixed(1) + '%" data-go="' + s.i + '" data-tip="step ' + s.i + " · " + num(s.tk[0]) + " input (" + num(s.tk[2]) + ' cached)"></i>'; }).join("") + "</div></section>" +
            (outOk ? '<section class="chart"><h3>Output tokens per step<span>up to ' + kfmt(maxOut) + '</span></h3><div class="bars out">' +
            tks.map(function (s) { return '<i style="height:' + (100 * s.tk[1] / maxOut).toFixed(1) + '%" data-go="' + s.i + '" data-tip="step ' + s.i + " · " + num(s.tk[1]) + ' output"></i>'; }).join("") + "</div></section>"
            : '<p class="muted small">Output tokens per step are not shown: this harness’s per-message counts do not add up to its run total.</p>');
        } else if (tk) {
          html += '<p class="muted small">This harness reports tokens for the whole run only, not per step.</p>';
        } else if (ts.length <= 1) {
          html += emptyState("No timing or token data per step.", "This harness recorded neither step times nor token counts.");
        }
        return html;
      }
      function bindRun() {
        $$("[data-go]", panel).forEach(function (el) {
          el.addEventListener("click", function () {
            var i = el.getAttribute("data-go"); history.replaceState(null, "", "#trajectory"); show("trajectory");
            var li = document.getElementById("s" + i); if (li) { li.scrollIntoView({block: "center", behavior: reduce ? "auto" : "smooth"}); li.classList.add("flash"); setTimeout(function () { li.classList.remove("flash"); }, 1600); }
          });
        });
      }
      function parse(t) { try { return t ? JSON.parse(t) : null; } catch (e) { return null; } }
      function summary() {
        var r = parse(d.result_json) || {}, c = parse(d.config_json) || {}, ep = r.episode || {}, meta = c.metadata || {};
        var reward = r.verifier_result && r.verifier_result.rewards ? r.verifier_result.rewards.reward : d.reward;
        var who = d.model_label ? d.model_label + " with " + d.harness_label : (c.harness || (r.agent_info || {}).name || "") + (c.model ? " with " + c.model : "");
        var steps = ep.steps_used != null ? num(ep.steps_used) + (ep.max_steps ? " of " + num(ep.max_steps) : "") + " simulator steps" : "";
        var parts = [];
        if (reward != null) parts.push("Reward " + rew(reward) + (ep.outcome ? ', outcome <span class="mono">' + h(ep.outcome) + "</span>" : ""));
        if (steps) parts.push(steps + (ep.requests != null ? " in " + num(ep.requests) + " robot requests" : ""));
        var wall = r.wall_time_s != null ? dur(r.wall_time_s) : "";
        var agent = [];
        if (r.agent_return_code != null) agent.push("exit code " + h(r.agent_return_code));
        if (r.agent_timed_out) agent.push("timed out");
        if (r.exception_info) agent.push("stopped by an exception");
        var result = '<section class="card sum"><h3>Result</h3><p>' + (parts[0] || "Not scored") + ".</p>" +
          (parts[1] ? "<p>" + parts[1] + (wall ? ", " + wall + " in all" : "") + ".</p>" : "") +
          (agent.length ? '<p class="muted">Agent: ' + agent.join(", ") + ".</p>" : "") +
          (ep.agent_text ? "<blockquote>" + h(ep.agent_text) + "</blockquote>" : "") + "</section>";
        var chips = [meta.source_benchmark, meta.category && meta.category.replace(/-/g, " "), meta.difficulty].filter(Boolean)
          .map(function (x) { return '<span class="chip">' + h(x) + "</span>"; }).join("") +
          (meta.tags || []).map(function (x) { return '<span class="chip tag">' + h(x) + "</span>"; }).join("");
        var setup = '<section class="card sum"><h3>Setup</h3><p>' + h(who || "Agent") +
          (c.agent_timeout_s ? ", " + dur(c.agent_timeout_s) + " agent time limit" : "") + (c.seed != null ? ", seed " + h(c.seed) : "") + ".</p>" +
          (c.task_path ? '<p class="muted">Task <code>' + h(c.task_path) + "</code></p>" : "") +
          (chips ? '<p class="chips">' + chips + "</p>" : "") +
          (c.sandbox ? '<p class="muted">Sandbox <code>' + h(c.sandbox) + "</code></p>" : "") + "</section>";
        return '<div class="sums">' + result + setup + "</div>";
      }
      /* the trial folder as the shared file tree: what is published opens in place, the rest says why it is not */
      function why(p) {
        if (p === "episode/recording.mp4") return "Not published here. The same recording is published as artifacts/recording.mp4.";
        if (/^agent\//.test(p)) return "Not published. Raw agent logs are not published; the Trajectory tab is built from them.";
        if (/(^|\/)trace\.jsonl$/.test(p)) return "Not published. The robot request trace is not published; the Recording and Trajectory tabs are built from it.";
        if (/\.log$|(^|\/)server/.test(p)) return "Not published. Server logs are not published.";
        if (/^episode\//.test(p)) return "Not published. Episode server files are not published; the Verdict tab summarizes how the episode ended.";
        if (/^verifier\//.test(p)) return "Not published. Only the verifier’s output and reward are published.";
        if (/^artifacts\//.test(p)) return "Not published. Only the recording and a sample of the camera images are published.";
        return "Not published. Only the files the viewer shows are published.";
      }
      function manifest() {
        var sp = d.sprite, tiles = {};
        (d.obs || []).forEach(function (o) { tiles[o[0]] = o; });
        var files = (d.files || []).map(function (f) {
          var p = f[0], e = {p: p, s: f[1]};
          if (p === "result.json" && d.result_json) e.t = d.result_json;
          else if (p === "config.json" && d.config_json) e.t = d.config_json;
          else if (p === "verifier/test-stdout.txt" && d.verdict && d.verdict.verifier) e.t = d.verdict.verifier;
          else if (p === "verifier/reward.txt" && d.reward != null) e.t = String(d.reward);
          else if (p === "artifacts/recording.mp4") { if (d.video) e.v = d.video; else e.w = "Not published. The recording has no video frames."; }
          else if (p === "agent/trajectory.json") {
            if (d.withheld) e.w = "Withheld. " + WITHHELD.replace(/^Trajectory not published: /, "").replace(/^./, function (c) { return c.toUpperCase(); });
            else { e.w = "Shown as the Trajectory tab. The raw file is not published; the Trajectory tab shows every step with its commands and outputs, redacted and clipped."; e.href = "#trajectory"; e.hrefLabel = "Open the Trajectory tab"; }
          } else if (/^artifacts\/observations\//.test(p)) {
            var o = tiles[p.split("/").pop()];
            if (o && sp) {
              var i = o[2];
              var u = sp.disp || sp.tile;  /* in display units: the file viewer draws the tile at twice this, the sprite's own size */
              e.sprite = {src: sp.src, x: (i % sp.cols) * u, y: Math.floor(i / sp.cols) * u, w: u, h: u,
                bw: Math.min(sp.n, sp.cols) * u, bh: Math.ceil(sp.n / sp.cols) * u,
                caption: (o[1] != null ? "Looked at in step " + o[1] + ". " : "") + "A " + sp.tile + " px thumbnail from the filmstrip; the full-size image is not published."};
            } else e.w = "Not published. Only a sample of " + (sp ? sp.n : 0) + " camera images is published, as the filmstrip on the Recording tab.";
          } else e.w = why(p);
          return e;
        });
        return {title: "Trial folder", root: d.id + "/", open: "result.json", files: files,
          note: "Raw agent logs, the robot request trace and server logs are not published; the Trajectory tab is built from them. Workspace paths read <code>&lt;workspace&gt;</code>."};
      }
      function files() {
        return summary() + '<h2 class="lab">Trial folder</h2>' + ((d.files || []).length ? '<div id="ftree" class="ftree"></div>' :
          emptyState("No files were recorded for this trial.", "The trial folder is empty; the tabs above show what the viewer has."));
      }
      function mountFiles() {
        var el = $("#ftree", panel); if (!el) return;
        if (window.FileTree) window.FileTree.mount(el, manifest(), {key: "files"});
        else el.innerHTML = emptyState("Could not load the file viewer.", "Reload the page to try again.");
      }
      show(location.hash.slice(1) || "recording");
    }).catch(function (err) {
      panel.setAttribute("aria-busy", "false");
      panel.innerHTML = emptyState("Could not load this trial’s data.", "The request failed (" + err.message + "). ", '<button type="button" class="tbtn" data-retry>Try again</button>');
      var b = $("[data-retry]", panel); if (b) b.addEventListener("click", function () { location.reload(); });
    });
  }

  /* ---------------------------------------------------------------- compare */
  function initCompare(root) {
    var p = new URLSearchParams(location.search), a = p.get("a"), b = p.get("b");
    getJSON("/runs/d/trials.json").then(function (idx) {
      root.setAttribute("aria-busy", "false");
      var T = idx.trials, byTask = {};
      Object.keys(T).forEach(function (id) { (byTask[T[id][0]] = byTask[T[id][0]] || []).push(id); });
      function label(id) { var t = T[id]; return mfirst(idx.hm[t[1]][0]) + " · " + (STATUS[t[2]] || t[2]) + (t[3] ? "" : " (not counted)"); }
      function sorted(ids) { return ids.slice().sort(function (x, y) { return (T[y][3] - T[x][3]) || (T[x][1] - T[y][1]) || (x < y ? -1 : 1); }); }
      var task = a && T[a] ? T[a][0] : b && T[b] ? T[b][0] : null;
      var tasks = Object.keys(byTask).sort();
      var picker = '<div class="cpick"><select data-task aria-label="Task"><option value="">Choose one of ' + Object.keys(byTask).length.toLocaleString("en-US") + " tasks…</option>" +
        tasks.map(function (k) { return '<option value="' + h(k) + '"' + (k === task ? " selected" : "") + ">" + h(k) + " · " + h(idx.titles[k] || "") + "</option>"; }).join("") + "</select>" +
        (task && idx.urls && idx.urls[task] ? '<a class="ln" href="' + h(idx.urls[task]) + '">Open task page</a>' : "") + "</div>";
      if (!task) { root.innerHTML = picker + emptyState("Pick a task to compare two of its trials.", "Or press Compare on a trial, or on a task page's results."); bindPick(); return; }
      var ids = sorted(byTask[task]);
      if (!a || !T[a]) a = ids.find(function (x) { return x !== b; });
      if (!b || !T[b] || b === a) b = ids.find(function (x) { return x !== a && T[x][1] !== T[a][1] && T[x][3]; }) || ids.find(function (x) { return x !== a; });
      root.innerHTML = picker + (b ? '<div class="cbar"><button type="button" class="btn quiet sm" data-both>Play both from the start</button><span class="muted">Each column follows its own video; click a step to seek.</span></div>'
        : '<p class="muted">This task has only one trial.</p>') +
        '<div class="cmpgrid"><div class="col" data-side="a"></div><div class="col" data-side="b"></div></div>';
      bindPick();
      [["a", a], ["b", b]].forEach(function (sd) { if (sd[1]) column(sd[0], sd[1], ids); });
      var both = $("[data-both]", root);
      if (both) both.addEventListener("click", function () { $$("video", root).forEach(function (v) { v.currentTime = 0; v.playbackRate = 0.5; play(v); }); });
      function bindPick() {
        var s = $("[data-task]", root);
        s.addEventListener("change", function () { if (!s.value) return; var l = sorted(byTask[s.value]); location.search = "?a=" + encodeURIComponent(l[0]) + (l[1] ? "&b=" + encodeURIComponent(l.find(function (x) { return x !== l[0] && T[x][1] !== T[l[0]][1]; }) || l[1]) : ""); });
      }
      function column(side, id, ids) {
        var el = $('[data-side="' + side + '"]', root);
        el.innerHTML = '<select aria-label="Trial ' + side.toUpperCase() + '" data-full>' + ids.map(function (x) { return '<option value="' + h(x) + '"' + (x === id ? " selected" : "") + ">" + h(label(x)) + "</option>"; }).join("") +
          '</select><div class="cbody" aria-busy="true"><div class="vbox skel"></div><span class="skel" style="width:60%;height:14px;margin-top:12px"></span></div>';
        $("select", el).addEventListener("change", function (e) { var q = new URLSearchParams(location.search); q.set(side, e.target.value); location.search = "?" + q.toString(); });
        var body = $(".cbody", el);
        getJSON("/runs/d/" + id + ".json").then(function (d) {
          var st = d.status, vd = d.verdict;
          body.setAttribute("aria-busy", "false");
          body.innerHTML = '<div class="vbox">' + (d.video ? '<video src="' + h(d.video) + '" controls controlslist="nodownload noplaybackrate noremoteplayback" disablepictureinpicture muted playsinline preload="auto"></video>' : '<div class="novideo empty-state"><b>No recording.</b>The episode ended before a frame was written.</div>') + "</div>" +
            '<p class="who"><span class="badge ' + st + '">' + STATUS[st] + '</span><a class="wl" href="/runs/t/' + h(id) + '/">' + (d.mark || "") + h(d.label || mfirst(idx.hm[d.hm][0])) + "</a></p>" +
            '<dl class="facts"><div><dt>Reward</dt><dd>' + rew(d.reward) + '</dd></div><div><dt>Outcome</dt><dd class="mono">' + h(d.outcome || "–").replace(/_/g, "_<wbr>") + "</dd></div><div><dt>Env steps</dt><dd>" + num(d.steps_used) + " / " + num(d.max_steps) +
            "</dd></div><div><dt>Requests</dt><dd>" + num(d.requests) + "</dd></div><div><dt>Wall</dt><dd>" + dur(d.wall) + "</dd></div></dl>" +
            (d.withheld ? '<div class="withheld" role="note"><b>Trajectory withheld</b><p>The agent looked at files outside its workspace.</p></div>' : (vd.claim_text ? '<p class="said"><span class="muted">' + ({done: "robo done", give_up: "robo give-up", runner: "closed by the runner"}[vd.claim] || "last message") + ": </span>" + h(vd.claim_text.replace(/^\[runner\]\s*/, "").slice(0, 400)) + "</p>" : "") +
              (d.steps.length ? '<ol class="slist">' + stepListHTML(d) + "</ol>" : '<p class="muted">No trajectory was recorded.</p>'));
          keyActivate(body);
          var v = $("video", body);
          if (!v) return;
          v.playbackRate = 0.5;
          var sy = syncVideo(v, d, function (i) {
            $$(".cur", body).forEach(function (x) { x.classList.remove("cur"); });
            var li = i == null ? null : $('.slist li[data-i="' + i + '"]', body);
            if (li) { li.classList.add("cur"); scrollInto(li); }
          });
          body.addEventListener("click", function (e) { var li = e.target.closest("[data-t0]"); if (li) { sy.pin(li.getAttribute("data-i")); seekTo(v, li.getAttribute("data-t0")); } });
        }).catch(function (err) { body.innerHTML = emptyState("Could not load this trial.", "The request failed (" + err.message + ")."); });
      }
    }).catch(function (err) { root.innerHTML = emptyState("Could not load the list of trials.", "The request failed (" + err.message + ")."); });
  }

  /* ---------------------------------------------------------------- task page: pick two trials to compare */
  function initCompareTicks() {
    var boxes = $$("[data-cmp]"), go = $("[data-cmp-go]"), hint = $("[data-cmp-hint]");
    if (!boxes.length || !go) return;
    function upd() {
      var on = boxes.filter(function (b) { return b.checked; });
      go.disabled = on.length !== 2;
      boxes.forEach(function (b) { b.disabled = !b.checked && on.length >= 2; });
      if (hint) hint.textContent = on.length === 2 ? "Two trials selected." : on.length === 1 ? "Tick one more trial." : "Tick two trials to compare them side by side.";
    }
    boxes.forEach(function (b) { b.addEventListener("change", upd); });
    go.addEventListener("click", function () {
      var on = boxes.filter(function (b) { return b.checked; }).map(function (b) { return b.getAttribute("data-cmp"); });
      if (on.length === 2) location.href = "/runs/compare/?a=" + encodeURIComponent(on[0]) + "&b=" + encodeURIComponent(on[1]);
    });
    upd();
  }

  $$("[data-list]").forEach(function (root) { if (root.getAttribute("data-list") === "tasks") initTasks(root); else initList(root); });
  var mx = $(".scroll.mx"); if (mx) initMatrix(mx);
  if (document.body.getAttribute("data-trial")) initTrial(document.body.getAttribute("data-trial"));
  var cmp = $("#compare"); if (cmp) initCompare(cmp);
  initCompareTicks();
  document.addEventListener("modelset", fit);
  fit();
})();
