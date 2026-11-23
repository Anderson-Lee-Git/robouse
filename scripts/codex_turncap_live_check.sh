#!/usr/bin/env bash
# Live check of the Codex turn cap (src/robouse/harnesses/turncap.py): one real Codex trial at --max-turns 3 on a light
# task (cubepick-reach-layout-0), with the login in an explicitly named credential folder. It confirms that Codex
# runs the PreModelRequest/PostModelRequest hooks, that the runner stops it before model request 4, and that the
# trial ends as a Claude Code trial at --max-turns does.
#
#   scripts/codex_turncap_live_check.sh CODEX_CREDENTIAL_DIR EXPECTED_EMAIL [MODEL] [OUT]
#
# CODEX_CREDENTIAL_DIR  a folder holding the designated Codex login, auth.json (a ChatGPT subscription login). It is
#                       copied into a temporary home for this run only and never written back. Neither ~/.codex nor
#                       an inherited CODEX_HOME, OPENAI_API_KEY or account pool is used.
# EXPECTED_EMAIL        the account that login must belong to. There is no default, by design.
# MODEL                 the Codex model (default gpt-6-astra)
# OUT                   run folder (default runs/codex-turncap-live/<timestamp> in this checkout)
#
# It needs the network (the model), so it runs on a login node, not a compute node. It costs about four model
# requests. ROBOUSE_PYTHON selects the Python with robouse installed (default: python3).
# Exit codes: 0 passed, 1 failed, 2 refused (bad arguments or login), 3 inconclusive (the agent finished in fewer
# than 3 turns).
set -euo pipefail

die() { echo "codex turn-cap live check: $*" >&2; exit 2; }

[ $# -ge 2 ] || die "usage: $0 CODEX_CREDENTIAL_DIR EXPECTED_EMAIL [MODEL] [OUT]"
CRED=$(cd "$1" 2>/dev/null && pwd) || die "no folder $1"
EMAIL=$2
MODEL=${3:-gpt-6-astra}
ROOT=$(cd "$(dirname "$0")/.." && pwd)
OUT=${4:-$ROOT/runs/codex-turncap-live/$(date +%Y%m%d-%H%M%S)}
PY=${ROBOUSE_PYTHON:-python3}
[ -f "$CRED/auth.json" ] || die "$CRED has no auth.json"
[ -n "$EMAIL" ] || die "EXPECTED_EMAIL is empty"

# nothing inherited: no API key (that would bill the API), no account pool, no other Codex home
unset OPENAI_API_KEY CODEX_API_KEY ROBOUSE_CODEX_AUTH_DIR CODEX_HOME

# the login must be a ChatGPT subscription login of EXPECTED_EMAIL. Prints the account and plan only, never a token
"$PY" -I - "$CRED/auth.json" "$EMAIL" <<'EOF' || exit 2
import base64, json, sys
data = json.load(open(sys.argv[1]))
if data.get("auth_mode") != "chatgpt" or data.get("OPENAI_API_KEY"):
    sys.exit(f"not a ChatGPT subscription login (auth_mode={data.get('auth_mode')!r})")
part = ((data.get("tokens") or {}).get("id_token") or "..").split(".")[1]
claims = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)) or b"{}")
email = str(claims.get("email") or "").lower()
if email != sys.argv[2].strip().lower():
    sys.exit(f"the login belongs to {email or 'an unnamed account'}, not {sys.argv[2]}")
plan = (claims.get("https://api.openai.com/auth") or {}).get("chatgpt_plan_type")
print(f"codex login: {email} (plan {plan})")
EOF

command -v codex >/dev/null || die "codex is not on PATH"
echo "codex: $(codex --version)"

# a temporary home holding a copy of the login: robouse copies <home>/.codex/auth.json into the trial's own Codex home
REAL_HOME=$HOME
TMP_HOME=$(mktemp -d)
trap 'rm -rf "$TMP_HOME"' EXIT
mkdir -m 700 "$TMP_HOME/.codex"
cp "$CRED/auth.json" "$TMP_HOME/.codex/auth.json"
chmod 600 "$TMP_HOME/.codex/auth.json"
# the sandbox denies credential folders under $HOME; the real home's must stay denied too
DENY=$(HOME=$REAL_HOME "$PY" -c 'import glob, os
from robouse.runner.sandbox import HOME_DENIED
h = os.path.expanduser("~")
print(":".join(p for r in HOME_DENIED for p in glob.glob(os.path.join(h, r))))')
export ROBOUSE_SANDBOX_DENY="${ROBOUSE_SANDBOX_DENY:+$ROBOUSE_SANDBOX_DENY:}$DENY"
export ROBOUSE_CACHE_DIR=${ROBOUSE_CACHE_DIR:-$REAL_HOME/.cache/robouse}

mkdir -p "$OUT"
echo "trial: codex $MODEL, --max-turns 3, into $OUT"
HOME=$TMP_HOME "$PY" -m robouse.cli run --task "$ROOT/tasks/cubepick/cubepick-reach-layout-0" --harness codex \
  --model "$MODEL" --max-turns 3 --timeout 900 --out "$OUT" || true

"$PY" -I - "$OUT" <<'EOF'
import json, sys
from pathlib import Path

trials = sorted(Path(sys.argv[1]).glob("*/result.json"))
if not trials:
    sys.exit("FAIL: no trial result")
tdir = trials[-1].parent
res = json.loads(trials[-1].read_text())
cfg = json.loads((tdir / "config.json").read_text())
hc = cfg.get("harness_config") or {}
tc = res.get("turn_cap") or {}
ep = res.get("episode") or {}
print(f"trial {tdir}")
print(f"  config: max_turns={cfg.get('max_turns')} method={hc.get('max_turns_method')} "
      f"enforced={hc.get('max_turns_enforced')} codex={hc.get('codex_version')}")
print(f"  turn_cap: {json.dumps(tc)}")
print(f"  outcome={ep.get('outcome')} agent_text={ep.get('agent_text')!r} exception={res.get('exception_info')}")
problems = []
if hc.get("max_turns_method") != "codex-hooks" or hc.get("max_turns_enforced") is not True:
    problems.append("the trial did not use the hooks")
if res.get("exception_info"):
    problems.append("the trial failed on infrastructure")
if not tc.get("hook_events"):
    problems.append("no hook ever reported: Codex did not run the hooks")
if tc.get("reached"):
    if tc.get("reached_by") != "codex-hooks":
        problems.append(f"the cap was reached by {tc.get('reached_by')}, not the hooks")
    if tc.get("model_requests_completed") != 3:
        problems.append(f"{tc.get('model_requests_completed')} model requests completed, not 3")
    if ep.get("outcome") != "gave_up" or not str(ep.get("agent_text", "")).endswith("agent exited without robo done"):
        problems.append("the episode did not end as at Claude Code's --max-turns")
if problems:
    print("FAIL: " + "; ".join(problems))
    sys.exit(1)
if not tc.get("reached"):
    print(f"INCONCLUSIVE: the agent finished after {tc.get('model_requests_completed')} requests, before the cap")
    sys.exit(3)
print("PASS: Codex stopped before model request 4; the trial ended as at Claude Code's --max-turns")
EOF
