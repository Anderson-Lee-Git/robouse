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
  // a duration, the one way every robouse.ai page writes it (build_runs_site.fmt_s, build_hub.fmt_dur): "5.9 s", "43 s", "1 min 42 s", "1 h 5 min"
  function dur(x) {
    if (x == null) return ""; x = +x;
    if (x < 9.95) return x.toFixed(1) + " s";
    if (x < 59.5) return Math.round(x) + " s";
    var t = Math.round(x);
    if (t < 3600) return Math.floor(t / 60) + " min" + (t % 60 ? " " + (t % 60) + " s" : "");
    var m = Math.round(t / 60);
    return Math.floor(m / 60) + " h" + (m % 60 ? " " + (m % 60) + " min" : "");
  }
  function rew(x) { return x == null || isNaN(+x) ? "" : (+x).toFixed(1); }
  function mfirst(l) { var i = String(l).indexOf(" + "); return i < 0 ? l : l.slice(i + 3) + " · " + l.slice(0, i); }  // "Claude Code + Opus 5.5" -> "Opus 5.5 · Claude Code"
  function num(x) { return x == null ? "" : Number(x).toLocaleString("en-US"); }
  // a name whose hyphenated words never break at their hyphens (build_runs_site.nb; .nw in /ui.css)
  function nb(s) { return String(s == null ? "" : s).split(" ").map(function (w) { return w.indexOf("-") >= 0 ? '<span class="nw">' + h(w) + "</span>" : h(w); }).join(" "); }
  // a mark glued to its name's first word, never alone on a line (UI.named in /ui.js, build_runs_site.named)
  function named(mark, name) { var s = String(name == null ? "" : name), i = s.indexOf(" "); return mark ? '<span class="mkw">' + mark + nb(i < 0 ? s : s.slice(0, i)) + "</span>" + (i < 0 ? "" : " " + nb(s.slice(i + 1))) : nb(s); }
  function kfmt(x) { x = +x || 0; return x >= 1e6 ? (x / 1e6).toFixed(2) + "M" : x >= 1e4 ? Math.round(x / 1e3) + "k" : x >= 1e3 ? (x / 1e3).toFixed(1) + "k" : String(x); }
  function getJSON(u) { return fetch(u).then(function (r) { if (!r.ok) throw new Error(r.status + " " + u); return r.json(); }); }
  var coll = typeof Intl !== "undefined" ? new Intl.Collator(undefined, {numeric: true, sensitivity: "base"}) : null;
  function cmpText(a, b) { return coll ? coll.compare(a, b) : (a < b ? -1 : a > b ? 1 : 0); }
  var STATUS = {ok: "Solved", no: "Not solved", infra: "Infra failure", partial: "Stopped", budget: "Stopped at budget"};
  var reduce = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
  function setKeys() { return window.ModelSet && ModelSet.keys && ModelSet.pairs && ModelSet.pairs().length ? ModelSet.keys() : null; }
  function quiet(t) { return '<p class="muted small">' + h(t) + "</p>"; }  /* an empty section: one plain line, no placeholder box */
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
  /* a focused chart mark shows its tip by its own box (keyboard and touch have no pointer position) */
  document.addEventListener("focusin", function (e) {
    var el = e.target.closest && e.target.closest("[data-tip]"); if (!el) { hideTip(); return; }
    var r = el.getBoundingClientRect(); showTip({clientX: r.left + r.width / 2, clientY: r.bottom}, el.getAttribute("data-tip"));
  });
  document.addEventListener("focusout", hideTip);

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
    if (P.get("all") === "1") limit = Infinity;  /* "Show all" survives a reload or a shared link */
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
    function filtered() { return fsel.some(function (s) { return s.value; }) || !!(scope && scope.value === "all") || !!only; }
    function apply() {
      var n = 0;
      rows.forEach(function (r) { var ok = match(r); if (ok) n++; r.hidden = !ok || n > limit; });
      /* the count only while a search or filter narrows the list ("12 of 128 trials"); the page states the total once */
      if (count) count.textContent = n === rows.length || !n ? "" : fmt(n) + " of " + fmt(rows.length) + " " + noun;
      if (moreBox) { moreBox.hidden = n <= limit; more.textContent = "Show " + fmt(n - Math.min(n, limit)) + " more"; }
      if (empty) {
        empty.hidden = n > 0; wrap.hidden = n === 0;
        if (!n) {  /* one pattern: what matched nothing, and one button that undoes it */
          var word = q && q.value.trim(), filt = filtered();
          $("b", empty).textContent = "No " + noun + " match " + (filt ? "these filters" + (word ? " and “" + word + "”" : "") : "“" + word + "”") + ".";
          var cb = $("[data-lclear]", empty); if (cb) cb.textContent = filt ? "Clear filters" : "Clear search";
        }
      }
      if (!hook.noUrl) {
        var p = new URLSearchParams(location.search);
        fsel.forEach(function (s) { var k = s.getAttribute("data-lf"); if (s.value) p.set(k, s.value); else p.delete(k); });
        if (q) { if (q.value.trim()) p.set("q", q.value.trim()); else p.delete("q"); }
        if (scope) { if (scope.value === "all" && !only) p.set("scope", "all"); else p.delete("scope"); }
        if (hasPairs && !hook.noOnly) { if (only) p.set("m", only); else p.delete("m"); }
        var sth = ths.filter(function (x) { return x.getAttribute("aria-sort") !== "none" && x.getAttribute("data-key"); })[0];
        if (sth) { p.set("sort", sth.getAttribute("data-key")); p.set("dir", sth.getAttribute("aria-sort") === "ascending" ? "asc" : "desc"); } else { p.delete("sort"); p.delete("dir"); }
        if (limit === Infinity && limit0 !== Infinity) p.set("all", "1"); else p.delete("all");
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
      return s ? s.toLowerCase() : null;
    }
    function sortBy(th, dir) {
        var idx = [].indexOf.call(th.parentNode.children, th), isNum = th.getAttribute("data-sort") === "num";
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
    }
    ths.forEach(function (th) {
      var b = $("button.sb", th); if (!b) return;
      b.addEventListener("click", function () {
        var isNum = th.getAttribute("data-sort") === "num", cur = th.getAttribute("aria-sort");
        sortBy(th, cur === "none" ? (th.getAttribute("data-first") || (isNum ? "descending" : "ascending")) : cur === "descending" ? "ascending" : "descending");
        apply();
      });
    });
    /* an order from the URL (?sort=date&dir=asc) before the first draw */
    var s0 = P.get("sort") && ths.filter(function (x) { return x.getAttribute("data-key") === P.get("sort"); })[0];
    if (s0) sortBy(s0, P.get("dir") === "asc" ? "ascending" : "descending");
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
  // step text for people: long floats rounded, markdown marks dropped, the runner's episode line as a sentence
  // an agent's message as it wrote it: paragraphs, lists, **bold**, `code` (escaped first; nothing else is rendered)
  function mdLite(t) {
    var inl = function (x) { return h(x).replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>").replace(/(^|[\s(])\*([^*\s][^*]*)\*(?=[\s).,;:]|$)/g, "$1<i>$2</i>"); };
    var out = [], list = null;
    String(t || "").split(/\n/).forEach(function (line) {
      var m = line.match(/^\s*(?:[-*•]|(\d+)[.)])\s+(.*)$/);
      if (m) {
        var tag = m[1] ? "ol" : "ul";
        if (!list || list.tag !== tag) { if (list) out.push("</" + list.tag + ">"); list = {tag: tag}; out.push("<" + tag + ">"); }
        out.push("<li>" + inl(m[2]) + "</li>");
        return;
      }
      if (list) { out.push("</" + list.tag + ">"); list = null; }
      var hd = line.match(/^\s*#{1,6}\s+(.*)$/);
      if (hd) out.push("<p><b>" + inl(hd[1]) + "</b></p>");
      else if (line.trim()) out.push("<p>" + inl(line) + "</p>");
    });
    if (list) out.push("</" + list.tag + ">");
    return out.join("");
  }
  function tidy(t) {
    t = String(t || "");
    var m = t.match(/^episode: outcome=(\S+) success=(\S+)(?: steps_used=(\d+)\/(\d+))?/);
    if (m) return "Episode ended: " + (m[2] === "True" ? "solved" : oc(m[1]).toLowerCase()) + (m[3] ? ", " + num(+m[3]) + " of " + num(+m[4]) + " steps" : "") + ".";
    return t.replace(/-?\d+\.\d{4,}(e-?\d+)?/g, function (x) { return String(Math.round(parseFloat(x) * 1000) / 1000); })
      .replace(/\*\*|__|`/g, "").replace(/^#+\s*/, "");
  }
  // a command as typed, with each command after "&&" on its own line and every flag or hyphenated word whole, so a
  // narrow column wraps between words, never inside "--grip" (the text copies as the same command)
  function cmdHtml(a) {
    /* a command as lines: each "&&" ends its line and the next command starts indented; a line wider than the box wraps
       under itself with a hanging indent (runs.css .cl); a short flag or signed number stays whole ("--grip", "-0.12") */
    var tok = function (l) { return l.split(/( +)/).map(function (w) { return /-/.test(w) && w.trim() && w.length <= 32 ? '<span class="nw">' + h(w) + "</span>" : h(w); }).join(""); };
    return String(a || "").split("\n").map(function (line, n) {
      var parts = line.split(/ && (?=\S)/);
      return parts.map(function (c, k) {
        return '<span class="cl' + (k ? " ch" : "") + (n || k ? "" : " c0") + '">' + (tok(c) || " ") + (k < parts.length - 1 ? " &amp;&amp;" : "") + "</span>";
      }).join("");
    }).join("");
  }
  // a VLA runner's step note in words ("vla: 10 motion request(s)" -> "10 motion requests")
  function vlaText(t) { return String(t || "").replace(/^vla: (\d+) motion request\(s\)/, function (m, n) { return n + (n === "1" ? " motion request" : " motion requests"); }); }
  // a camera image's camera, from its file name, in words ("obs_003_topview.png" -> "Top camera")
  var CAMS = {topview: "Top camera", top: "Top camera", front: "Front camera", frontview: "Front camera", side: "Side camera", sideview: "Side camera",
    wrist: "Wrist camera", eye_in_hand: "Wrist camera", robot0_eye_in_hand: "Wrist camera", agentview: "Third-person camera", overview: "Overview camera",
    head: "Head camera", fpv: "Drone camera", birdview: "Bird's-eye camera", overhead: "Overhead camera"};
  function camName(f) {
    var c = String(f).replace(/\.png$/, "").replace(/^obs_\d+_?/, "");
    if (!c || /^\d+$/.test(c)) return "";
    return CAMS[c] || CAMS[c.replace(/^robot\d_/, "")] || c.replace(/^robot\d_/, "").replace(/_/g, " ").replace(/^./, function (x) { return x.toUpperCase(); }) + " camera";
  }
  function actionOf(s) {
    var r = actionRaw(s); r.text = tidy(r.text); return r;
  }
  // a multi-line command by its first meaningful line: `python3 -c "` or `cd /tmp && python3 - <<'EOF'` alone says
  // nothing, so the line after the opener that does something (a robo call first, not an import or a comment) joins it
  var OPENER = /(-c\s*["']|<<-?\s*['"]?\w+['"]?|&&|\\)\s*$/;
  function cmdLabel(a) {
    var lines = a.split("\n"), first = lines[0];
    if (lines.length < 2 || !OPENER.test(first)) return first;
    var body = lines.slice(1).map(function (l) { return l.trim(); }).filter(function (l) { return l && !/^(import |from \S+ import |#|["']\s*$|EOF$|PY$)/.test(l); });
    var pick = body.filter(function (l) { return /\brobo\s+\w/.test(l); })[0] || body[0];
    return pick ? first.replace(OPENER, "").trim() + " … " + pick : first;
  }
  function actionRaw(s) {
    if (s.c && s.c.length) {
      var a = cmdLabel(s.c[0].a);
      return {text: a + (s.c.length > 1 ? "  (+" + (s.c.length - 1) + (s.c.length > 2 ? " commands)" : " command)") : ""), cls: ""};
    }
    if (s.src === "system") return {text: vlaText((s.m || "").split("\n")[0]), cls: "sys"};
    return {text: vlaText(s.m || s.r || "").replace(/\s+/g, " "), cls: "msg"};
  }
  function exitOf(s) { return (s.c || []).some(function (c) { return c.x != null; }); }
  function sprStyle(sp, i, size) {
    size = size || sp.disp || sp.tile;
    var k = size / sp.tile, cols = Math.min(sp.n, sp.cols), rows = Math.ceil(sp.n / sp.cols);
    return "background-image:url(" + sp.src + ");background-size:" + (cols * sp.tile * k) + "px " + (rows * sp.tile * k) + "px;background-position:-" +
      ((i % sp.cols) * sp.tile * k) + "px -" + (Math.floor(i / sp.cols) * sp.tile * k) + "px";
  }
  /* the number a reader sees for a step: ATIF numbers the task prompt 1, so the steps after it count from 1, and the
     Trajectory badge, the lists and the Timing tab all agree */
  function base(d) { return d._base != null ? d._base : (d._base = d.prompt ? 1 : d.steps.length && d.steps[0].i > 1 ? d.steps[0].i - 1 : 0); }
  function sn(d, i) { return i == null ? i : i - base(d); }
  function stepListHTML(d) {
    return d.steps.map(function (s) {
      var a = actionOf(s), v = s.v;
      var x = s.env && s.env[1] > s.env[0] ? "+" + (s.env[1] - s.env[0]) + " sim steps" : "";  /* simulator steps this step moved, not commands */
      return '<li data-i="' + s.i + '"' + (v ? ' data-t0="' + v[0] + '" tabindex="0" aria-label="Step ' + sn(d, s.i) + ", " + h(a.text.slice(0, 120)) + ", seek to " + t2(v[0]) + '"' : ' class="nov"') +
        '><span class="i">' + sn(d, s.i) + '</span><span class="t">' + (v && x && v[0] > 0 ? t2(v[0]) : "") +  // the recording time where this step moved the robot; blank for steps that did not move it

        '</span><span class="a ' + a.cls + '" title="' + h(a.text.slice(0, 400)) + '">' + h(a.text.slice(0, 220)) + '</span><span class="x' + (exitOf(s) ? " err" : "") + '">' + (exitOf(s) ? "exit≠0" : x) + "</span></li>";
    }).join("");
  }
  function keyActivate(box) {  // Enter or space on a focusable step row seeks, like a click; ↑ ↓ Home End move between rows
    /* each list is one tab stop (the first row that seeks), not one per step */
    $$(".slist", box).forEach(function (ol) { $$("li[data-t0]", ol).forEach(function (li, k) { li.tabIndex = k ? -1 : 0; }); });
    box.addEventListener("keydown", function (e) {
      var li = e.target.matches && e.target.matches("li[data-t0]") ? e.target : null; if (!li) return;
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); e.stopPropagation(); li.click(); return; }
      var all = $$("li[data-t0]", li.parentNode), k = all.indexOf(li);
      var j = e.key === "ArrowDown" ? k + 1 : e.key === "ArrowUp" ? k - 1 : e.key === "Home" ? 0 : e.key === "End" ? all.length - 1 : -2;
      if (j === -2 || !all[j]) return;
      e.preventDefault(); e.stopPropagation(); li.tabIndex = -1; all[j].tabIndex = 0; all[j].focus();
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

  // a task's difficulty as every page shows it (build_hub.DIFFICULTY has the same map)
  var DIFFICULTY = {easy: "Easy", medium: "Medium", hard: "Hard"};
  // readable episode outcomes (the runner's codes stay in the raw JSON)
  var OUTCOMES = {success_reached: "Goal reached", done: "Agent said done", gave_up: "Agent gave up", budget_exhausted: "Step budget used up",
    agent_timeout: "Harness timeout", wall_time_exhausted: "Trial time limit", agent_exited: "Agent exited", "no result": "No result",
    budget_stop: "Stopped at the model budget"};
  function oc(x) { return x ? (OUTCOMES[x] || String(x).replace(/_/g, " ").replace(/^./, function (c) { return c.toUpperCase(); })) : ""; }
  // "Stopped at the $5 budget": a trial the model gateway stopped at its spend cap (build_runs_site.budget_text)
  function ocOf(d) { return d.outcome === "budget_stop" && d.budget_stop && d.budget_stop.cap_usd != null ? "Stopped at the $" + d.budget_stop.cap_usd + " budget" : oc(d.outcome); }
  var WITHHELD = "Trajectory not published: during this trial the agent looked at files outside its workspace (for example listing the home folder or searching the whole disk), so its commands and their outputs may show unrelated local files. The recording, the camera images, the reward and the outcome are shown.";
  // a trial whose model received no camera images (its recorded image_input; build_runs_site.noimg_tag on the server-built pages)
  var NOIMG = '<span class="noimg" title="The model never received camera images as input. On vision tasks it read the saved camera frames with Python it wrote, using the camera matrices from robo info where the task provides them.">no image input</span>';

  /* ---------------------------------------------------------------- trial page */
  function initTrial(id) {
    if (!$("#stage")) return;  /* a trial that never ran: the header says why, there is nothing to load */
    var stage = $("#stage"), panel = $("#panel"), player = $("#player"), v = $("#vid"), pctl = $(".pctl", player);
    /* the stage's top (set as the page loads) moves when the header rewraps in a resized window; runs.css sizes the player from it */
    if (stage && v) window.addEventListener("resize", function () { stage.style.setProperty("--top", Math.round(stage.getBoundingClientRect().top + scrollY) + "px"); });
    if (v) v.removeAttribute("controls");  /* native controls are the no-script fallback; the page has its own */
    var below = document.createElement("div"); below.id = "below"; stage.parentNode.insertBefore(below, stage.nextSibling);
    var tabs = $$("nav.tabs [role=tab]");
    function tabOf(hash) { var t = (hash || "").replace(/^#/, "").split("/")[0]; if (t === "run") t = "timing"; return /^(recording|trajectory|verdict|timing|files)$/.test(t) ? t : "recording"; }  // #run: the tab's old address
    stage.className = "stage t-" + tabOf(location.hash);
    tabs.forEach(function (a) { a.setAttribute("aria-selected", a.getAttribute("data-tab") === tabOf(location.hash) ? "true" : "false"); a.tabIndex = a.getAttribute("aria-selected") === "true" ? 0 : -1; });
    getJSON("/runs/d/" + id + ".json").then(function (d) {
      var current = null, sync = null;
      /* a VLA policy is never "the agent"; its runner's done at the end of the step budget is the budget running out (as
         the run page says, build_runs_site) */
      var vla = d.kind === "vla", WHO = vla ? "the policy" : "the agent";
      function ocT(x) {
        if (vla && x === "done" && d.steps_used != null && d.max_steps && d.steps_used >= d.max_steps - 1) x = "budget_exhausted";
        var t = oc(x); return vla ? t.replace(/^Agent\b/, "Policy") : t;
      }
      /* per-step output counts that add up to under half the run's total are not counts of output: only input is shown */
      function tokOk() {
        var tk = d.tokens, sum = d.steps.reduce(function (a, s) { return a + (s.tk ? s.tk[1] : 0); }, 0);
        return !tk || sum >= 0.5 * (tk.out || 0);
      }
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
        /* the speed: three buttons, or on touch screens one that cycles 0.25×, 0.5×, 1× (the control row fits a phone) */
        var setSpeed = function () {
          $$("[data-speed]", pctl).forEach(function (x) { x.setAttribute("aria-pressed", +x.getAttribute("data-speed") === speed ? "true" : "false"); });
          var cyc = $('[data-k="speed"]', pctl); if (cyc) { cyc.textContent = speed + "×"; cyc.setAttribute("aria-label", "Playback speed " + speed + "×, change"); }
        };
        setSpeed();
        v.addEventListener("timeupdate", function () { var p = pct(v.currentTime); knob.style.left = p + "%"; laneEl.setAttribute("aria-valuenow", Math.round(p)); laneEl.setAttribute("aria-valuetext", t2(v.currentTime)); });
        var setPlay = function () { var on = !v.paused; playB.classList.toggle("on", on); playB.setAttribute("aria-label", on ? "Pause" : "Play"); };
        v.addEventListener("play", setPlay); v.addEventListener("pause", setPlay); v.addEventListener("ended", setPlay);
        /* drag along the lane to scrub (the recording follows the pointer), tap or click to jump. A finger moves the
           recording only once it moves sideways: a vertical swipe that starts on the lane scrolls the page (runs.css
           touch-action:pan-y) and leaves the recording where it was */
        var scrub = function (e) { var r = laneEl.getBoundingClientRect(); seekTo(v, Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)) * dur0()); };
        laneEl.addEventListener("pointerdown", function (e) {
          if (e.button) return;
          laneEl.setPointerCapture(e.pointerId); laneEl._x = e.clientX;
          laneEl._drag = e.pointerType === "mouse" || e.pointerType === "pen" ? 2 : 1;
          if (laneEl._drag === 2) { v.pause(); scrub(e); }
        });
        laneEl.addEventListener("pointermove", function (e) {
          if (laneEl._drag === 1 && Math.abs(e.clientX - laneEl._x) > 4) { laneEl._drag = 2; v.pause(); }
          if (laneEl._drag === 2) scrub(e);
        });
        var endDrag = function (e) {
          if (!laneEl._drag) return;
          if (laneEl._drag === 1 && e.type === "pointerup") { v.pause(); scrub(e); }  /* a tap: jump there */
          laneEl._drag = 0; try { laneEl.releasePointerCapture(e.pointerId); } catch (err) {}
        };
        laneEl.addEventListener("pointerup", endDrag); laneEl.addEventListener("pointercancel", endDrag);
        laneEl.addEventListener("keydown", function (e) {
          if (e.key === "ArrowUp" || e.key === "ArrowDown") { step(e.key === "ArrowUp" ? 1 : -1); e.preventDefault(); }
          else if (e.key === "Home") { seekTo(v, 0); e.preventDefault(); }
          else if (e.key === "End") { seekTo(v, dur0()); e.preventDefault(); }
          else if (e.key === "PageUp" || e.key === "PageDown") { seekTo(v, v.currentTime + (e.key === "PageUp" ? -5 : 5)); e.preventDefault(); }
        });
        pctl.addEventListener("click", function (e) {
          var b = e.target.closest("button"); if (!b || b.disabled) return;
          if (b.hasAttribute("data-speed") || b.getAttribute("data-k") === "speed") {
            speed = b.hasAttribute("data-speed") ? +b.getAttribute("data-speed") : SPEEDS[(SPEEDS.indexOf(speed) + 1) % SPEEDS.length];
            v.playbackRate = speed; try { localStorage.setItem("runs-speed", speed); } catch (err) {}
            setSpeed();
          } else if (b.getAttribute("data-k") === "play") { if (v.paused) play(v); else v.pause(); }
          else if (b.getAttribute("data-k") === "full") fullscreen();
          else step(b.getAttribute("data-k") === "next" ? 1 : -1);
        });
        var prevB = $('[data-k="prev"]', pctl), nextB = $('[data-k="next"]', pctl), seekable = d.steps.filter(function (s) { return s.v; });
        var ends = function (i) {  /* Previous and Next stop at the first and the last step (before the first, there is no previous) */
          if (!seekable.length) return;
          var k = seekable.findIndex(function (s) { return s.i === i; });
          prevB.disabled = k <= 0; nextB.disabled = k >= seekable.length - 1;
        };
        ends(null);
        sync = syncVideo(v, d, function (i) {
          ends(i);
          $$(".cur[data-i]").forEach(function (el) { el.classList.remove("cur"); });
          if (i == null) { now.innerHTML = ""; return; }
          $$('[data-i="' + i + '"]').forEach(function (el) { el.classList.add("cur"); });
          var s = d.steps.find(function (x) { return x.i === i; });
          now.innerHTML = '<span class="ns">Step ' + h(sn(d, i)) + "</span>" + (s ? '<span class="na">\u00a0· ' + h(actionOf(s).text.slice(0, 80)) + "</span>" : "");
          scrollInto($('.slist li[data-i="' + i + '"]'));
          markTiles(i);
        });
        /* the player's keys work only while the player shows (not on Timing or Files) and, for Space and the arrows, only
           while focus is in the player: elsewhere they scroll the page as usual */
        document.addEventListener("keydown", function (e) {
          if (busyTarget(e) || !player || !player.offsetParent || !player.getClientRects().length) return;
          var tag = (e.target || {}).tagName || "", inside = player.contains(document.activeElement);
          if ((e.key === "ArrowRight" || e.key === "ArrowLeft" || e.key === " ") && !inside) return;
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
        if (v && (tab === "timing" || tab === "files")) v.pause();
        below.innerHTML = "";
        panel.innerHTML = ({recording: recording, trajectory: trajectory, verdict: verdict, timing: run, files: files})[tab]();
        panel.setAttribute("aria-busy", "false");
        if (tab === "recording" && d.sprite) below.innerHTML = strip();
        if (tab === "timing") bindRun();
        if (tab === "files") mountFiles();
        if (sync) { var i = sync.now(); if (i != null) { $$('[data-i="' + i + '"]').forEach(function (el) { el.classList.add("cur"); }); markTiles(i); } }
        /* a phone's tab bar scrolls: the selected tab is always in view */
        var on = tabs.filter(function (a) { return a.getAttribute("aria-selected") === "true"; })[0], bar = on && on.parentNode;
        if (on && bar && bar.scrollWidth > bar.clientWidth) {
          var br = bar.getBoundingClientRect(), tr = on.getBoundingClientRect();
          if (tr.left < br.left) bar.scrollLeft -= br.left - tr.left + 24; else if (tr.right > br.right) bar.scrollLeft += tr.right - br.right + 24;
        }
        if (tab === "trajectory" && /\/prompt$/.test(location.hash)) {  /* "Task prompt" in the Recording list: the prompt, open */
          var pr = $("details.prompt", panel); if (pr) { pr.open = true; pr.scrollIntoView({block: "start"}); }
        }
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
        if (!d.steps.length) return quiet("No trajectory was recorded for this trial.");
        var n = d.steps.length;  /* the same count as the Trajectory tab: every step listed */
        var first = d.steps[0] && d.prompt ? '<li class="nov"><span class="i"></span><span class="t"></span><span class="a msg"><a href="#trajectory/prompt">Task prompt</a></span><span class="x"></span></li>' : "";
        return '<div class="recbox"><div class="rechead"><span title="Click a step to seek; ← → to step">Steps</span></div><ol class="slist">' + first + stepListHTML(d) + "</ol>" +
          (d.hidden ? '<p class="muted small slnote">' + d.hidden + " one-action steps in the middle are not listed.</p>" : "") + tailNote() + "</div>";
      }
      /* a harness log that stops before the episode did (the agent kept moving until the time limit): say so, so the
         recording's last part is not read as missing */
      function tailNote() {
        var last = null;
        d.steps.forEach(function (s) { if (s.env && s.env[1] != null) last = Math.max(last || 0, s.env[1]); });
        if (last == null || d.steps_used == null || d.steps_used - last <= Math.max(50, 0.2 * d.steps_used)) return "";
        return '<p class="muted small slnote">The harness logged steps up to simulator step ' + num(last) + " of " + num(d.steps_used) + "; the rest of the recording has no step in this list.</p>";
      }
      function strip() {
        var sp = d.sprite;
        return '<section class="strip" id="filmstrip" aria-label="Camera images"><div class="rechead"><span>' + (d.image_input === false ? "Camera images saved during the episode; the model received no images" : "Camera images the agent looked at") + '</span><span class="num">' +
          (sp.total > sp.n ? sp.n + " of " + sp.total + " shown" : sp.total) + '</span></div><div class="tiles" data-fade>' +
          d.obs.map(function (o) {
            var cam = camName(o[0]);  // the camera, from the file name, in words
            var lab = o[1] != null ? "Step " + sn(d, o[1]) + (cam ? ", " + cam : "") : o[0].replace(/\.png$/, "");
            var two = o[1] != null ? "<b>Step " + h(sn(d, o[1])) + "</b>" + (cam ? "<small>" + h(cam) + "</small>" : "") : h(lab);
            return '<button type="button" class="tile"' + (o[1] != null ? ' data-s="' + o[1] + '"' : "") + (o[3] != null ? ' data-seek="' + o[3] + '"' : "") + ' title="' + h(o[0]) + '" aria-label="Camera image, ' + h(lab) + (o[3] != null ? ", seek the recording here" : "") + '"><i style="' + sprStyle(sp, o[2]) + '"></i><span>' + two + "</span></button>";
          }).join("") + "</div></section>";
      }
      function trajectory() {
        var out = [];
        if (d.prompt) out.push('<details class="disc prompt"><summary>Task prompt</summary><div class="txt">' + h(d.prompt) + "</div></details>");
        if (d.withheld) return out.join("") + withheldNote();
        if (!d.steps.length) return out.join("") + quiet("No trajectory was recorded for this trial.");
        out.push('<ol class="traj">');
        var prev = null, outOk = tokOk();
        d.steps.forEach(function (s) {
          if (d.hidden && prev != null && s.i - prev > 1) out.push('<li class="gap">… ' + d.hidden + " one-action steps not shown …</li>");
          prev = s.i;
          var moved = !!(s.v && s.env && s.env[1] > s.env[0]);
          var head = '<div class="sh"><span class="num">' + sn(d, s.i) + "</span>" + (s.src !== "agent" ? '<span class="src">' + ({system: "System", user: "Prompt"}[s.src] || h(s.src)) + "</span>" : "") +
            (s.ts != null ? '<span class="num">+' + dur(s.ts) + "</span>" : "") +
            (s.tk ? (outOk ? '<span class="num" title="Input and output tokens of this step">' + kfmt(s.tk[0]) + " in" + "\u00a0" + "·" + "\u00a0" + kfmt(s.tk[1]) + " out</span>"
              : '<span class="num" title="Input tokens of this step">' + kfmt(s.tk[0]) + " in</span>") : "") +
            (moved ? '<button type="button" class="seek" data-seek="' + s.v[0] + '" title="Seek the recording here">' + t2(s.v[0]) + "</button>" : "") + "</div>";
          var body = "", ep = s.src === "system" && /^episode: /.test(s.m || "");
          if (ep) {  /* the runner's closing line ("episode: outcome=done success=True steps_used=677/1400") as the Verdict says it */
            var vl = verdictLine(), em = s.m.match(/steps_used=(\d+)\/(\d+)/), rw = s.m.match(/verifier reward: ([\d.]+)/);
            body += '<p class="vline ' + vl[1] + '">' + h(vl[0]) + "</p>" +
              (em || rw ? '<p class="muted small">' + [em ? num(+em[1]) + " of " + num(+em[2]) + " steps" : "", rw ? "verifier reward " + rew(+rw[1]) : ""].filter(Boolean).join(", ") + ".</p>" : "");
          } else if (s.m) body += '<div class="txt' + (s.src === "agent" ? " md" : "") + '">' + (s.src === "agent" ? mdLite(vlaText(s.m)) : h(vlaText(s.m))) + "</div>";
          if (s.r) body += '<details class="disc rsn"><summary>Reasoning</summary><div class="txt md">' + mdLite(s.r) + "</div></details>";
          (s.c || []).forEach(function (c) {
            body += '<pre class="cmd"><code>' + cmdHtml(c.a) + "</code></pre>";
            if (c.b) body += '<pre class="out"><code>' + h(c.b) + "</code></pre>";
            if (c.img && d.sprite) body += '<div class="imgs">' + c.img.map(function (k) { return '<i style="' + sprStyle(d.sprite, k) + '"></i>'; }).join("") + "</div>";
            var imgOnly = c.o != null && /^(\s*\[image\]\s*)+$/.test(c.o), nImg = imgOnly ? c.o.match(/\[image\]/g).length : 0;
            if (imgOnly) { if (!(c.img && d.sprite)) body += quiet("The output is " + (nImg === 1 ? "an image" : nImg + " images") + ", not published."); }  /* no "[image] [image]" text */
            else if (c.o != null) body += '<details class="disc res"' + (c.n <= 8 ? " open" : "") + "><summary>Output · " + c.n + " line" + (c.n === 1 ? "" : "s") + (c.x != null ? ' · <span class="x-err">exit ' + h(c.x) + "</span>" : "") + '</summary><pre class="out"><code>' + h(c.o) + "</code></pre></details>";
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
        return '<section class="xg"><h2>' + h(title) + '</h2><dl>' + rows.map(function (r) {
          return '<div' + (r[3] ? ' title="' + h(r[3]) + '"' : "") + "><dt>" + h(r[0]) + '</dt><dd><span class="xv">' + h(r[1]) + "</span>" + (r[2] ? ' <span class="xu">' + h(r[2]) + "</span>" : "") + "</dd></div>";
        }).join("") + "</dl>" + (note || "") + "</section>";
      }
      function verdictExtras() {
        var out = "";
        if (X.metrics) out += grp("Episode metrics", X.metrics.map(function (m) { return [m[0], m[1], m[2], m[3] ? "Better: " + m[3] : ""]; }));
        if (X.placement) { var p = X.placement; out += grp("Placement", [["Split", p.split], ["Objects moved", p.objects != null ? String(p.objects) : null], ["Largest offset", p.max_cm != null ? p.max_cm.toFixed(1) : null, "cm"], ["Placement seed", p.seed != null ? String(p.seed) : null]]); }
        if (X.mode && X.mode !== "sim") out += grp("Embodiment", [["Mode", {real: "Real robot", "hil-mock": "Hardware in the loop (mock)"}[X.mode] || X.mode]]);  /* every published trial is simulated: no card for that */
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
        if (X.cost && !vla && X.cost.source !== "no model") { var c = X.cost; out += grp("Cost", [["Prompt tokens", c.prompt != null ? num(c.prompt) : null], ["Cached", c.cached ? num(c.cached) : null], ["Completion tokens", c.completion != null ? num(c.completion) : null], ["Cost", c.usd != null ? "$" + (+c.usd).toFixed(c.usd < 1 ? 4 : 2) : null, "USD"], ["Source", c.source || null]]); }
        if (X.vla) { var v = X.vla; out += grp("Policy inference", [["Inferences", num(v.inferences)], ["Chunk size", v.chunk != null ? String(v.chunk) : null, "actions"], ["Round trip", v.roundtrip ? v.roundtrip[0].toFixed(2) + " s median, " + v.roundtrip[1].toFixed(2) + " s p90" : null], ["Server", v.server ? v.server[0].toFixed(2) + " s median, " + v.server[1].toFixed(2) + " s p90" : null]]); }
        return out ? '<div class="xgs">' + out + "</div>" : "";
      }
      /* the runner's own note ("[runner] agent exited without robo done") as a sentence, without the log tag */
      function unrunner(t) { t = String(t || ""); if (!/^\[runner\]/.test(t)) return t; t = t.replace(/^\[runner\]\s*/, ""); return t.charAt(0).toUpperCase() + t.slice(1) + (/[.!?]$/.test(t) ? "" : "."); }
      /* the Verdict's one sentence and its class; the Trajectory's closing line says the same */
      function verdictLine() {
        var vd = d.verdict, r = d.reward, solved = r != null && r > 0, oc0 = d.outcome, claim = vla ? "" : vd.claim;
        var limit = {budget_exhausted: "the step budget ran out", wall_time_exhausted: "the time limit was reached", agent_timeout: WHO + " ran out of time"}[oc0];
        if (d.status === "infra") return ["Not scored: an infrastructure failure ended the trial.", "warn"];
        if (d.status === "partial") return ["Not scored: the run was stopped before this trial finished.", "warn"];
        if (solved) return [claim === "done" ? "Solved: the agent said done and the simulator confirmed the goal."
          : claim === "give_up" ? "Solved: the agent refused, which was the expected answer."
          : oc0 === "success_reached" ? "Solved: the simulator saw the goal reached, which ended the episode."
          : "Solved: " + WHO + " stopped" + (vla ? "" : " without saying done") + ", and the final state met the goal.", "ok"];
        return [claim === "done" ? "Not solved: the agent said done, but the goal wasn’t reached."
          : claim === "give_up" ? "Not solved: the agent gave up."
          : limit ? "Not solved: " + limit + " before the goal was reached."
          : "Not solved: " + WHO + " stopped" + (vla ? "" : " without saying done") + ", and the goal wasn’t reached.", "no"];
      }
      function verdict() {
        var vd = d.verdict, vl = verdictLine(), line = vl[0], cls = vl[1];
        var rows = [];  /* steps and time are in the header, robot requests on Timing: the Verdict is the sentence and what is not said elsewhere */
        var log = vd.infra && vd.infra.length ? '<details class="disc errlog"><summary>Error log</summary><pre class="out wrap"><code>' + h(vd.infra.join("\n\n")) + "</code></pre></details>" : "";
        return '<div class="vd1"><p class="vline ' + cls + '">' + h(line) + "</p>" +
          (rows.length ? '<table class="vt"><tbody>' + rows.map(function (x) { return '<tr><th scope="row">' + h(x[0]) + "</th><td>" + h(x[1]) + "</td></tr>"; }).join("") + "</tbody></table>" : "") +
          log + "</div>" + verdictExtras();
      }
      function run() {
        var tk = d.tokens, stats = [];
        /* wall time, robot requests and env steps are in the facts above the tabs; this tab adds only what is new */
        stats.push(["Episode", dur(d.ep_wall), ""]);
        stats.push(["Video", dur(d.duration), "robot moving"]);
        /* "Steps" are simulator steps (the facts above); the Trajectory tab's list is its own count */
        var nAgent = d.steps.filter(function (s) { return s.src === "agent"; }).length, nAll = d.steps.length + (d.hidden || 0);
        stats.push(["Trajectory entries", num(nAll || null), nAll && nAgent !== d.steps.length ? num(nAgent + (d.hidden || 0)) + " by " + WHO : ""]);
        if (d.motion != null) stats.push(["Robot requests", num(d.requests), num(d.motion) + " moved the robot"]);
        var html = '<dl class="stats">' + stats.filter(function (s) { return s[1] !== ""; }).map(function (s) { return "<div><dt>" + s[0] + '</dt><dd class="num">' + s[1] + (s[2] ? '<span class="vh"> </span><small>' + s[2] + "</small>" : "") + "</dd></div>"; }).join("");
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
            var tipT = dur(dt) + " before step " + sn(d, ts[k + 1].i) + "\n" + actionOf(ts[k + 1]).text.slice(0, 120);
            return '<i role="button" tabindex="' + (k ? -1 : 0) + '" style="flex:' + Math.max(dt, T / 2000).toFixed(3) + ' 0 0" data-go="' + ts[k + 1].i + '" data-i="' + ts[k + 1].i + '" data-tip="' + h(tipT) + '" aria-label="' + h(tipT.replace("\n", ": ")) + '"></i>';  /* data-i: the selected step's segment is marked .cur, like its row in the lists */
          });
          html += '<section class="chart"><h2>Wall clock between steps<span>' + dur(T) + " from the first step to the last; each segment is the time before a step (" + (vla ? "the previous actions running, then the policy’s next inference" : "the previous command running, then the model thinking") + "). Select one for the step.</span></h2>" +
            '<div class="tl" role="group" aria-label="Time before each step">' + segs.join("") + '</div><div class="axis num"><span>0 s</span><span>' + dur(T / 2) + "</span><span>" + dur(T) + "</span></div></section>";
        }
        var tks = d.steps.filter(function (s) { return s.tk; }), outOk = tokOk();
        if (tks.length > 1) {
          var maxIn = Math.max.apply(null, tks.map(function (s) { return s.tk[0]; })) || 1, maxOut = Math.max.apply(null, tks.map(function (s) { return s.tk[1]; })) || 1;
          html += '<section class="chart"><h2>Input tokens per step<span>the context the model read, up to ' + kfmt(maxIn) + '</span></h2><div class="bars">' +
            tks.map(function (s, k) { var t = "Step " + sn(d, s.i) + ": " + num(s.tk[0]) + " input tokens (" + num(s.tk[2]) + " cached)"; return '<i role="button" tabindex="' + (k ? -1 : 0) + '" style="height:' + (100 * s.tk[0] / maxIn).toFixed(1) + '%" data-go="' + s.i + '" data-tip="' + h(t) + '" aria-label="' + h(t) + '"></i>'; }).join("") + "</div></section>" +
            (outOk ? '<section class="chart"><h2>Output tokens per step<span>up to ' + kfmt(maxOut) + '</span></h2><div class="bars out">' +
            tks.map(function (s, k) { var t = "Step " + sn(d, s.i) + ": " + num(s.tk[1]) + " output tokens"; return '<i role="button" tabindex="' + (k ? -1 : 0) + '" style="height:' + (100 * s.tk[1] / maxOut).toFixed(1) + '%" data-go="' + s.i + '" data-tip="' + h(t) + '" aria-label="' + h(t) + '"></i>'; }).join("") + "</div></section>"
            : '<p class="muted small">Output tokens per step are not shown: this harness’s per-message counts do not add up to its run total.</p>');
        } else if (tk) {
          html += '<p class="muted small">This harness reports tokens for the whole run only, not per step.</p>';
        } else if (ts.length <= 1) {
          html += quiet("This harness recorded neither step times nor token counts.");
        }
        return html;
      }
      function bindRun() {
        function go(el) {
          var i = el.getAttribute("data-go"), st = d.steps.find(function (s) { return s.i === +i; });
          if (v && sync && st && st.v) { v.pause(); sync.pin(+i); seekTo(v, st.v[0]); }  /* the step is selected: the player shows it too */
          history.replaceState(null, "", "#trajectory"); show("trajectory");
          var li = document.getElementById("s" + i); if (li) { li.scrollIntoView({block: "center", behavior: reduce ? "auto" : "smooth"}); li.classList.add("flash"); setTimeout(function () { li.classList.remove("flash"); }, 1600); }
        }
        $$("[data-go]", panel).forEach(function (el) {
          el.addEventListener("click", function () { go(el); });
          /* a chart is one tab stop: ← → (and Home, End) move between its marks, Enter or Space opens the step */
          el.addEventListener("keydown", function (e) {
            if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(el); return; }
            var all = $$("[data-go]", el.parentNode), k = all.indexOf(el);
            var j = e.key === "ArrowRight" || e.key === "ArrowDown" ? k + 1 : e.key === "ArrowLeft" || e.key === "ArrowUp" ? k - 1 : e.key === "Home" ? 0 : e.key === "End" ? all.length - 1 : -2;
            if (j === -2 || !all[j]) return;
            e.preventDefault(); el.tabIndex = -1; all[j].tabIndex = 0; all[j].focus();
          });
        });
      }
      function parse(t) { try { return t ? JSON.parse(t) : null; } catch (e) { return null; } }
      function summary() {
        var r = parse(d.result_json) || {}, c = parse(d.config_json) || {}, ep = r.episode || {}, meta = c.metadata || {};
        var reward = r.verifier_result && r.verifier_result.rewards ? r.verifier_result.rewards.reward : d.reward;
        var who = d.model_label ? d.model_label + " with " + d.harness_label : (c.harness || (r.agent_info || {}).name || "") + (c.model ? " with " + c.model : "");
        var steps = ep.steps_used != null ? num(ep.steps_used) + (ep.max_steps ? " of " + num(ep.max_steps) : "") + " simulator steps" : "";
        var parts = [], scored = d.status !== "infra" && d.status !== "partial";
        /* the reward, outcome, steps and time are in the header and the Verdict: this card says only what the folder adds */
        var wall = r.wall_time_s != null ? dur(r.wall_time_s) : "";
        var agent = [];
        if (r.agent_return_code != null && +r.agent_return_code !== 0) agent.push("exit code " + h(r.agent_return_code));  /* a clean exit is not news */
        if (r.agent_timed_out) agent.push("timed out");
        if (r.exception_info) agent.push("stopped by an exception");
        /* the runner's note ("agent timed out") when the lines above already say it */
        function said(t) { var x = unrunner(t).toLowerCase().replace(/[.\s]+$/, ""); return x === ocT(ep.outcome).toLowerCase() || (r.agent_timed_out && /timed out$/.test(x)) || (vla && /step budget reached$/.test(x)); }
        var rbody = (agent.length ? "<p>" + (vla ? "Policy" : "Agent") + " process: " + agent.join(", ") + ".</p>" : "") +
          (ep.agent_text && !said(ep.agent_text) ? "<blockquote>" + h(unrunner(ep.agent_text)) + "</blockquote>" : "");
        var result = rbody ? '<section class="card sum"><h2>Result</h2>' + rbody + "</section>" : "";
        var cat = meta.category ? meta.category.replace(/-/g, " ") : "";  // "Rule inference", as the task page's chips
        var chips = [cat && cat.charAt(0).toUpperCase() + cat.slice(1), DIFFICULTY[meta.difficulty] ? DIFFICULTY[meta.difficulty] + " difficulty" : meta.difficulty].filter(Boolean)
          .map(function (x) { return '<span class="chip">' + h(x) + "</span>"; }).join("") +
          (meta.tags || []).map(function (x) { return '<span class="chip tag">' + h(x) + "</span>"; }).join("");
        var setup = '<section class="card sum"><h2>Setup</h2><p>' + h(vla && d.model_label ? d.model_label + ", a VLA policy" : who || "Agent") +
          (c.agent_timeout_s ? ", " + dur(c.agent_timeout_s) + (vla ? " time limit" : " agent time limit") : "") + (c.seed != null ? ", seed " + h(c.seed) : "") + ".</p>" +
          (d.hub ? '<p>Task: <a class="ln" href="' + h(d.hub) + '">' + h(d.title || c.task) + "</a></p>" : "") +
          (chips ? '<p class="chips">' + chips + "</p>" : "") + "</section>";
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
          else if (p === "episode/recording.mp4" && d.video) { e.w = why(p); e.href = "#files/artifacts/recording.mp4"; e.hrefLabel = "Open artifacts/recording.mp4"; }
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
                caption: (o[1] != null ? (d.image_input === false ? "Named in step " : "Looked at in step ") + sn(d, o[1]) + ". " : "") + "A " + sp.tile + " px thumbnail from the filmstrip; the full-size image is not published."};
            } else e.w = "Not published. Only a sample of " + (sp ? sp.n : 0) + " camera images is published, as the filmstrip on the Recording tab.";
          } else e.w = why(p);
          return e;
        });
        /* the root by its task and trial, not the folder name (which carries the harness's internal id); Copy path keeps the folder */
        return {title: "Trial folder", root: d.id + "/", rootLabel: d.task + " · " + String(d.id).split("__").pop(), open: "result.json", files: files,
          note: "Workspace paths read <code>&lt;workspace&gt;</code>."};
      }
      function files() {
        return summary() + '<h2 class="lab">Trial folder</h2>' + ((d.files || []).length ? '<div id="ftree" class="ftree"></div>' :
          quiet("No files were recorded for this trial."));
      }
      function mountFiles() {
        var el = $("#ftree", panel); if (!el) return;
        if (window.FileTree) window.FileTree.mount(el, manifest(), {key: "files"});
        else el.innerHTML = emptyState("Could not load the file viewer.", "Reload the page to try again.");
      }
      if (location.hash === "#run") history.replaceState(null, "", location.pathname + location.search + "#timing");  // the tab's old address, kept working
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
    // each pair's mark (/models.json `icon`), for the trial pickers' options (data-mark, drawn by /ui.js)
    var icons = getJSON("/models.json").then(function (m) { var o = {}; (m.pairs || []).forEach(function (q) { o[q.key] = q.icon || ""; }); return o; }, function () { return {}; });
    var IDX = null;
    function markOptions(sel) {
      icons.then(function (ic) {
        if (!IDX) return;
        [].forEach.call(sel.options, function (o) { var t = IDX.trials[o.value]; if (t) o.setAttribute("data-mark", ic[IDX.hm[t[1]][1]] || ""); });
        if (sel._lb && sel._lb.sync) sel._lb.sync();
      });
    }
    getJSON("/runs/d/trials.json").then(function (idx) {
      IDX = idx;
      root.setAttribute("aria-busy", "false");
      var T = idx.trials, byTask = {};
      Object.keys(T).forEach(function (id) { (byTask[T[id][0]] = byTask[T[id][0]] || []).push(id); });
      function label(id) { var t = T[id]; return mfirst(idx.hm[t[1]][0]) + " · " + (STATUS[t[2]] || t[2]) + (t[3] ? "" : " (not counted)"); }
      function sorted(ids) { return ids.slice().sort(function (x, y) { return (T[y][3] - T[x][3]) || (T[x][1] - T[y][1]) || (x < y ? -1 : 1); }); }
      var notes = [], a0 = a, b0 = b;
      if (a && !T[a]) { notes.push("No trial " + a + "."); a = null; }
      if (b && !T[b]) { notes.push("No trial " + b + "."); b = null; }
      var task = a ? T[a][0] : b ? T[b][0] : null;
      if (a && b && T[b][0] !== task) { notes.push("Trial B was a trial of another task (" + (idx.titles[T[b][0]] || T[b][0]) + "); both columns show " + (idx.titles[task] || task) + "."); b = null; }
      if (a && b === a) { notes.push("Trial A and B were the same trial; B is another trial of this task."); b = null; }
      var note = notes.length ? '<p class="cnote" role="status">' + h(notes.join(" ")) + "</p>" : "";
      var tasks = Object.keys(byTask).sort();
      var picker = '<div class="cpick"><select data-task aria-label="Task"><option value="" disabled hidden' + (task ? "" : " selected") + ">Choose a task</option>" +
        tasks.map(function (k) { return '<option value="' + h(k) + '" data-sub="' + h(k) + '"' + (k === task ? " selected" : "") + ">" + h(idx.titles[k] || k) + "</option>"; }).join("") + "</select>" +
        (task && idx.urls && idx.urls[task] ? '<a class="ln" href="' + h(idx.urls[task]) + '">Open task page</a>' : "") + "</div>";
      if (!task) { if (a0 || b0) history.replaceState(null, "", location.pathname + location.hash); root.innerHTML = picker + note + quiet("Pick a task, then two of its trials; Compare on a trial page opens this with that trial."); bindPick(); return; }
      var ids = sorted(byTask[task]);
      if (!a || !T[a]) a = ids.find(function (x) { return x !== b; });
      if (!b) b = ids.find(function (x) { return x !== a && T[x][1] !== T[a][1] && T[x][3]; }) || ids.find(function (x) { return x !== a; });
      if (a !== a0 || b !== b0) {  /* the address names the trials shown */
        var q = new URLSearchParams(location.search); q.set("a", a); if (b) q.set("b", b); else q.delete("b");
        history.replaceState(null, "", location.pathname + "?" + q.toString() + location.hash);
      }
      root.innerHTML = picker + note + (b ? '<div class="cbar"><button type="button" class="btn quiet sm" data-both>Play both from the start at 0.5×</button><span class="muted">Each column follows its own video; click a step to seek.</span></div>'
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
        markOptions($("select", el));
        var body = $(".cbody", el);
        getJSON("/runs/d/" + id + ".json").then(function (d) {
          var st = d.status, vd = d.verdict;
          body.setAttribute("aria-busy", "false");
          var facts = [["Outcome", st === "ok" || st === "infra" ? "" : ocOf(d)], ["Steps", d.steps_used != null ? num(d.steps_used) + (d.max_steps ? " of " + num(d.max_steps) : "") : ""],
            ["Time", dur(d.wall)], ["Reward", d.reward != null && +d.reward !== 0 && +d.reward !== 1 ? rew(d.reward) : ""]].filter(function (f) { return f[1]; });
          var said = d.withheld || st === "infra" || d.kind === "vla" ? "" : String(vd.claim_text || "").replace(/^\[runner\]\s*/, "");  /* a policy says nothing; "vla: step budget reached" is its runner's note */
          /* the recording at near its own size (a quarter larger at most) and in its own shape, as on the trial page */
          var vs = d.size && d.size[0] ? ' style="--ar:' + d.size[0] + "/" + d.size[1] + ";max-width:" + Math.min(560, Math.round(d.size[0] * 1.25)) + 'px"' : "";
          body.innerHTML = (d.video ? '<div class="vbox"' + vs + '><video src="' + h(d.video) + '" poster="' + h(d.video.replace("/runs/v/", "/runs/p/").replace(/\.mp4$/, ".jpg")) + '" controls controlslist="nodownload noplaybackrate noremoteplayback" disablepictureinpicture muted playsinline preload="metadata"></video></div>' : "") +
            /* the trial picker above names the trial; here its result, and a link to its page */
            '<p class="who"><span class="badge ' + st + '">' + STATUS[st] + '</span><a class="ln" href="/runs/t/' + h(id) + '/">Trial page</a>' + (d.image_input === false ? (d.noimg_note ? NOIMG.replace(/title="[^"]*"/, 'title="' + h(d.noimg_note) + '"') : NOIMG) : "") + "</p>" +
            (facts.length ? '<dl class="facts">' + facts.map(function (f) { return "<div><dt>" + f[0] + "</dt><dd>" + h(f[1]) + "</dd></div>"; }).join("") + "</dl>" : "") +
            (d.withheld ? '<div class="withheld" role="note"><b>Trajectory withheld</b><p>The agent looked at files outside its workspace.</p></div>' : (said ? '<p class="said"><span class="muted">' + (vd.claim === "done" || vd.claim === "give_up" ? "The agent: " : "Its last message: ") + "</span>" + h(said.slice(0, 400)) + "</p>" : "") +
              (d.steps.length ? '<ol class="slist">' + stepListHTML(d) + "</ol>" : quiet(d.video ? "No trajectory was recorded." : "No recording or trajectory: the trial ended before the agent acted.")));
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
