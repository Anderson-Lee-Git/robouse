#!/usr/bin/env python3
"""One page to see every robouse trial: runs/_gallery/index.html. See docs/viewer.md.

  .venv/bin/python tools/site/build_gallery.py [--runs runs] [--viewer http://127.0.0.1:8768]

A self-contained HTML file (no network, no build step) with a filterable table of all trials under runs/
(task, suite, source benchmark, harness, model, reward, outcome, env steps, wall time, audit flags) and a
card per trial with its video (relative link to <job>/<trial>/artifacts/recording.mp4), the agent's final
message and a link to the trial in the full viewer (tools/ops/view.sh). Reads runs/_audit/audit.json when
present (run tools/analysis/audit.py first to get the audit column). Open it straight from disk or serve runs/.
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

REPO = Path(__file__).resolve().parents[2]
DEFAULT_MODELS = {"claude-code": "claude-opus-5-5", "codex": "gpt-6-astra", "claude-code-glm": "zai-org/GLM-5.3",
                  "codex-glm": "zai-org/GLM-5.3", "mini-swe-agent-glm": "zai-org/GLM-5.3", "oracle": "scripted", "noop": "none"}
PROVIDER_PREFIXES = (("claude-", "anthropic"), ("gpt-", "openai"), ("gemini-", "google"))


def rj(p: Path):
    try:
        return json.loads(p.read_text(errors="replace"))
    except (OSError, ValueError):
        return None


def viewer_href(base: str, job: str, trial: str, task: str, harness: str, model: str | None) -> str:
    """The trial page of the BenchFlow viewer: /jobs/<job>/tasks/<source>/<agent>/<provider>/<model>/<task>/trials/<trial>,
    with the provider/model split the viewer itself uses (formats._bf_split_model)."""
    provider, name = None, model
    if model and "/" in model:
        provider, name = model.split("/", 1)
    elif model:
        provider = next((p for pre, p in PROVIDER_PREFIXES if model.lower().startswith(pre)), None)
    parts = ["_", harness or "_", provider or "_", name or "_", task]
    return f"{base}/jobs/{quote(job, safe='')}/tasks/" + "/".join(quote(p, safe="") for p in parts) + f"/trials/{quote(trial, safe='')}"


def final_message(d: Path, harness: str) -> str:
    t = rj(d / "agent" / "trajectory.json")
    if t is None and (d / "episode").exists():
        try:
            sys.path.insert(0, str(REPO / "src"))
            from robouse.atif import build

            t = build(d, harness)[0]
        except Exception:
            t = None
    if isinstance(t, dict):
        for st in reversed(t.get("steps") or []):
            if st.get("source") == "agent" and isinstance(st.get("message"), str) and st["message"].strip() and st.get("llm_call_count") != 0:
                return st["message"].strip()
    return ""


def collect(runs: Path, viewer: str) -> list[dict]:
    audit = rj(runs / "_audit" / "audit.json") or {}
    by_path = {t["path"]: t for t in audit.get("trials", [])}
    rows = []
    for cfg_p in sorted(runs.glob("*/*/config.json")):
        d = cfg_p.parent
        if d.parent.name.startswith(("_", ".")):
            continue
        cfg = rj(cfg_p) or {}
        res = rj(d / "result.json") or {}
        ep = rj(d / "episode" / "result.json") or res.get("episode") or {}
        harness = cfg.get("harness") or (res.get("agent_info") or {}).get("name") or "?"
        model = ((res.get("agent_info") or {}).get("model_info") or {}).get("name") or cfg.get("model") or DEFAULT_MODELS.get(harness)
        meta = cfg.get("metadata") or {}
        reward = ((res.get("verifier_result") or {}).get("rewards") or {}).get("reward")
        if reward is None:
            try:
                reward = float((d / "verifier" / "reward.txt").read_text().strip())
            except (OSError, ValueError):
                reward = None
        a = by_path.get(str(d.resolve())) or {}
        video = next((r for r in ("artifacts/recording.mp4", "episode/recording.mp4") if (d / r).is_file()), None)
        task = cfg.get("task") or res.get("task_name") or d.name.split("__")[0]
        status = "running" if not res and not a.get("infra_failure") and a.get("running", True) else ("done" if res else "incomplete")
        rows.append({
            "job": d.parent.name, "trial": d.name, "task": task, "suite": meta.get("suite") or "",
            "source": meta.get("source_benchmark") or res.get("source") or "", "difficulty": meta.get("difficulty") or "",
            "harness": harness, "model": model or "", "reward": reward, "outcome": ep.get("outcome") or ("running" if status == "running" else "no episode result"),
            "steps": ep.get("steps_used"), "max_steps": ep.get("max_steps"), "wall": res.get("wall_time_s"),
            "started": res.get("started_at") or cfg.get("started_at") or "", "status": status,
            "video": f"../{quote(d.parent.name)}/{quote(d.name)}/{video}" if video else None,
            "done_text": (ep.get("agent_text") or "")[:1500], "final": final_message(d, harness)[:3000],
            "viewer": viewer_href(viewer, d.parent.name, d.name, task, harness, model),
            "flags": [f"{f['severity']}: {f['id']}" for f in a.get("flags", []) if f.get("severity") in ("high", "medium")],
            "suspicious": bool(a.get("suspicious")), "infra": bool(a.get("infra_failure")),
            "motion": (a.get("checks") or {}).get("motion_requests"),
        })
    rows.sort(key=lambda r: (r["task"], r["harness"], r["model"], r["started"]))
    return rows


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>robouse · all trials</title>
<style>
:root{--fg:#111;--mut:#6b6b6b;--line:#e6e6e6;--ok:#127a3a;--bad:#b42318;--warn:#a15c00;--bg2:#fafafa}
*{box-sizing:border-box}body{margin:0;background:#fff;color:var(--fg);font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif}
main{max-width:1280px;margin:0 auto;padding:40px 24px 80px}h1{font-size:28px;font-weight:600;letter-spacing:-.01em;margin:0 0 4px}
.sub{color:var(--mut);margin:0 0 28px}.stats{display:flex;gap:32px;flex-wrap:wrap;margin:0 0 28px}.stat b{display:block;font-size:22px;font-weight:600}.stat span{color:var(--mut);font-size:12px}
.filters{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:0 0 12px;position:sticky;top:0;background:#fff;padding:10px 0;z-index:2;border-bottom:1px solid var(--line)}
select,input{font:inherit;border:1px solid var(--line);border-radius:6px;padding:5px 8px;background:#fff;color:var(--fg)}input[type=search]{min-width:220px}
.seg{display:inline-flex;border:1px solid var(--line);border-radius:6px;overflow:hidden}.seg button{font:inherit;border:0;background:#fff;padding:5px 10px;cursor:pointer;color:var(--mut)}.seg button.on{background:var(--fg);color:#fff}
.tw{max-height:60vh;overflow:auto;border-bottom:1px solid var(--line)}thead th{position:sticky;top:0;background:#fff;z-index:1}
table{width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-weight:500;color:var(--mut);cursor:pointer;user-select:none;white-space:nowrap}th:hover{color:var(--fg)}td.n{text-align:right;font-variant-numeric:tabular-nums}
tr:hover td{background:var(--bg2)}a{color:inherit}a.task{font-weight:500;text-decoration:none}a.task:hover{text-decoration:underline}
.r1{color:var(--ok);font-weight:600}.r0{color:var(--bad);font-weight:600}.muted{color:var(--mut)}.tag{display:inline-block;font-size:11px;border:1px solid var(--line);border-radius:4px;padding:0 5px;margin:1px 2px 1px 0;white-space:nowrap}
.tag.s{border-color:#f0b4ae;color:var(--bad)}.tag.i{border-color:#f3d19c;color:var(--warn)}
h2{font-size:18px;font-weight:600;margin:48px 0 16px}.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(360px,1fr));gap:20px}
.card{border:1px solid var(--line);border-radius:10px;overflow:hidden;display:flex;flex-direction:column}.card video{width:100%;aspect-ratio:1/1;background:#f3f3f3;display:block;object-fit:contain}
.novideo{aspect-ratio:1/1;background:#f6f6f6;display:flex;align-items:center;justify-content:center;color:var(--mut)}
.cb{padding:12px 14px;display:flex;flex-direction:column;gap:6px}.cb .top{display:flex;justify-content:space-between;gap:8px;align-items:baseline}.cb .meta{color:var(--mut);font-size:12px}
.msg{font-size:12.5px;white-space:pre-wrap;max-height:9.5em;overflow:auto;background:var(--bg2);border-radius:6px;padding:8px}.msg.done{max-height:4.8em}
.links{font-size:12px;display:flex;gap:12px}.more{margin:16px 0;text-align:center}.more button{font:inherit;border:1px solid var(--line);background:#fff;border-radius:6px;padding:6px 14px;cursor:pointer}
footer{color:var(--mut);font-size:12px;margin-top:48px}
</style></head><body><main>
<h1>robouse · all trials</h1>
<p class="sub">Every trial under <code>runs/</code>: an LLM agent (or the oracle / no-op control) drives a simulated robot through the <code>robo</code> CLI; the episode server records the video and judges success. Generated __GENERATED__.</p>
<div class="stats" id="stats"></div>
<div class="filters">
 <input type="search" id="q" placeholder="search task, trial, message…">
 <select id="f-harness"></select><select id="f-model"></select><select id="f-suite"></select><select id="f-source"></select><select id="f-job"></select>
 <span class="seg" id="f-reward"><button data-v="" class="on">all</button><button data-v="1">solved</button><button data-v="0">failed</button></span>
 <span class="seg" id="f-audit"><button data-v="" class="on">any</button><button data-v="flag">flagged</button><button data-v="sus">suspicious</button><button data-v="infra">infra</button></span>
 <span class="muted" id="count"></span>
</div>
<div class="tw"><table><thead><tr>
 <th data-k="task">task</th><th data-k="suite">suite</th><th data-k="source">source benchmark</th><th data-k="harness">harness</th><th data-k="model">model</th>
 <th data-k="reward" class="n">reward</th><th data-k="outcome">outcome</th><th data-k="steps" class="n">env steps</th><th data-k="wall" class="n">wall s</th><th data-k="flags">audit</th><th></th>
</tr></thead><tbody id="rows"></tbody></table></div>
<h2>Trials</h2>
<div class="cards" id="cards"></div>
<div class="more"><button id="more" hidden>show more</button></div>
<footer>Built by tools/site/build_gallery.py. Videos are linked relatively (<code>../&lt;job&gt;/&lt;trial&gt;/artifacts/recording.mp4</code>); "viewer" links need <code>tools/ops/view.sh</code> running at __VIEWER__. Audit column from runs/_audit/audit.json (tools/analysis/audit.py).</footer>
</main>
<script>
const DATA = __DATA__;
const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const st = {q:"", harness:"", model:"", suite:"", source:"", job:"", reward:"", audit:"", sort:"task", dir:1, shown:48};
function opts(id, key, label){ const vals=[...new Set(DATA.map(r=>r[key]).filter(Boolean))].sort(); const el=$(id);
  el.innerHTML=`<option value="">${label}: all</option>`+vals.map(v=>`<option>${esc(v)}</option>`).join(""); el.onchange=()=>{st[key]=el.value; st.shown=48; draw();}; }
opts("#f-harness","harness","harness"); opts("#f-model","model","model"); opts("#f-suite","suite","suite"); opts("#f-source","source","source"); opts("#f-job","job","job");
for (const [id,key] of [["#f-reward","reward"],["#f-audit","audit"]]) $(id).onclick=e=>{ if(!e.target.dataset) return; if(e.target.tagName!=="BUTTON") return;
  [...$(id).children].forEach(b=>b.classList.toggle("on",b===e.target)); st[key]=e.target.dataset.v; st.shown=48; draw(); };
$("#q").oninput=e=>{st.q=e.target.value.toLowerCase(); st.shown=48; draw();};
document.querySelectorAll("th[data-k]").forEach(th=>th.onclick=()=>{ const k=th.dataset.k; st.dir = st.sort===k ? -st.dir : 1; st.sort=k; draw(); });
$("#more").onclick=()=>{st.shown+=48; draw();};
function keep(r){
  if (st.harness && r.harness!==st.harness) return false; if (st.model && r.model!==st.model) return false;
  if (st.suite && r.suite!==st.suite) return false; if (st.source && r.source!==st.source) return false; if (st.job && r.job!==st.job) return false;
  if (st.reward==="1" && !(r.reward>0)) return false; if (st.reward==="0" && (r.reward>0 || r.reward==null)) return false;
  if (st.audit==="flag" && !r.flags.length) return false; if (st.audit==="sus" && !r.suspicious) return false; if (st.audit==="infra" && !r.infra) return false;
  if (st.q && !(r.task+" "+r.trial+" "+r.final+" "+r.done_text+" "+r.outcome).toLowerCase().includes(st.q)) return false;
  return true; }
function cmp(a,b){ const k=st.sort; let x=a[k], y=b[k]; if (Array.isArray(x)) {x=x.length; y=y.length;}
  if (x==null && y==null) return 0; if (x==null) return 1; if (y==null) return -1; return (x>y?1:x<y?-1:0)*st.dir; }
function rew(r){ return r.reward==null ? '<span class="muted">–</span>' : `<span class="${r.reward>0?'r1':'r0'}">${r.reward}</span>`; }
function tags(r){ return (r.suspicious?'<span class="tag s">suspicious</span>':'')+(r.infra?'<span class="tag i">infra</span>':'')+
  r.flags.slice(0,3).map(f=>`<span class="tag ${f.startsWith('high')?'s':''}" title="${esc(f)}">${esc(f.split(': ')[1])}</span>`).join("")+(r.flags.length>3?`<span class="muted">+${r.flags.length-3}</span>`:""); }
function draw(){
  const rows = DATA.filter(keep).sort(cmp);
  $("#count").textContent = `${rows.length} of ${DATA.length} trials`;
  const solved = rows.filter(r=>r.reward>0).length, scored = rows.filter(r=>r.reward!=null).length;
  const hs = new Set(rows.map(r=>r.harness+" · "+r.model)), tasks = new Set(rows.map(r=>r.task));
  $("#stats").innerHTML = [[rows.length,"trials"],[tasks.size,"tasks"],[hs.size,"harness · model pairs"],[scored?Math.round(100*solved/scored)+"%":"–","solved ("+solved+"/"+scored+")"],
    [rows.filter(r=>r.suspicious).length,"suspicious"],[rows.filter(r=>r.infra).length,"infra failures"]].map(([b,s])=>`<div class="stat"><b>${b}</b><span>${s}</span></div>`).join("");
  $("#rows").innerHTML = rows.map(r=>`<tr><td><a class="task" href="#c-${esc(r.job)}-${esc(r.trial)}">${esc(r.task)}</a><div class="muted" style="font-size:11px">${esc(r.job)}</div></td>
    <td>${esc(r.suite)}</td><td class="muted">${esc(r.source)}</td><td>${esc(r.harness)}</td><td>${esc(r.model)}</td><td class="n">${rew(r)}</td>
    <td>${esc(r.outcome)}</td><td class="n">${r.steps??"–"}${r.max_steps?`<span class="muted">/${r.max_steps}</span>`:""}</td><td class="n">${r.wall??"–"}</td><td>${tags(r)}</td>
    <td><a href="${esc(r.viewer)}" target="_blank">viewer</a></td></tr>`).join("");
  const shown = rows.slice(0, st.shown);
  $("#cards").innerHTML = shown.map(r=>`<div class="card" id="c-${esc(r.job)}-${esc(r.trial)}">
    ${r.video?`<video src="${esc(r.video)}" controls preload="metadata" muted playsinline loop></video>`:`<div class="novideo">no video (${esc(r.outcome)})</div>`}
    <div class="cb"><div class="top"><b>${esc(r.task)}</b>${rew(r)}</div>
    <div class="meta">${esc(r.harness)} · ${esc(r.model)} · ${esc(r.outcome)} · ${r.steps??"–"} steps · ${r.wall??"–"} s${r.motion!=null?` · ${r.motion} motion requests`:""}</div>
    ${tags(r)?`<div>${tags(r)}</div>`:""}
    ${r.final?`<div class="msg" title="the agent's last message">${esc(r.final)}</div>`:""}
    ${r.done_text?`<div class="msg done" title="robo done / give-up message">robo done: ${esc(r.done_text)}</div>`:""}
    <div class="links"><a href="${esc(r.viewer)}" target="_blank">open in viewer</a>${r.video?`<a href="${esc(r.video)}" target="_blank">video</a>`:""}<a href="../${esc(r.job)}/${esc(r.trial)}/" target="_blank">files</a></div>
    </div></div>`).join("");
  $("#more").hidden = rows.length <= st.shown;
}
draw();
</script></body></html>
"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", type=Path, default=REPO / "runs")
    ap.add_argument("--viewer", default="http://127.0.0.1:8768", help="base URL of tools/ops/view.sh")
    a = ap.parse_args(argv)
    rows = collect(a.runs, a.viewer.rstrip("/"))
    out = a.runs / "_gallery"
    out.mkdir(parents=True, exist_ok=True)
    data = json.dumps(rows, ensure_ascii=False).replace("</", "<\\/")
    page = (PAGE.replace("__DATA__", data)
            .replace("__GENERATED__", html.escape(datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")))
            .replace("__VIEWER__", html.escape(a.viewer)))
    (out / "index.html").write_text(page)
    print(f"wrote {out / 'index.html'} ({len(rows)} trials)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
