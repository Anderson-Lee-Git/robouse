"""The runs viewer's pair and counting rules for provider-routed models (tools/site/build_runs_site.py): old and new trial
folders of a pair are one column, a pair rerun under a new condition counts only its new trials (the old ones stay
published as earlier runs), budget stops are their own labelled result, and a column whose model got no images says so."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
# a maintainer tool (not in the package), written for Python 3.12
pytestmark = [
    pytest.mark.maintainer,
    pytest.mark.skipif(sys.version_info < (3, 12), reason="tools/site/build_runs_site.py needs Python 3.12"),
]


@pytest.fixture
def site():
    spec = importlib.util.spec_from_file_location("build_runs_site", ROOT / "tools" / "site" / "build_runs_site.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.HM[:] = [
        {
            "key": "codex-glm",
            "harness": "codex-glm",
            "model": "zai-org/GLM-5.3",
            "label": "GLM-5.3 · Codex",
            "model_label": "GLM-5.3",
            "harness_label": "Codex",
            "count_only": {"image_input": True},
        },
        {
            "key": "mini-glm",
            "harness": "mini-swe-agent-glm",
            "model": "zai-org/GLM-5.3",
            "label": "GLM-5.3 · mini-swe-agent",
            "model_label": "GLM-5.3",
            "harness_label": "mini-swe-agent",
        },
    ]
    mod.HM_KEY.clear()
    mod.HM_KEY.update({mod.canon(p["harness"], p["model"]): i for i, p in enumerate(mod.HM)})
    return mod


def _trial(site, name, harness, model, task, started, **kw):
    t = {
        "trial": name,
        "harness": harness,
        "model": model,
        "task": task,
        "started": started,
        "seed": None,
        "hm": site.pair_of(harness, model),
        "infra": False,
        "partial": False,
        "solved": False,
        "budget": None,
        "image_input": None,
        "cfg": {},
    }
    t.update(kw)
    return t


def test_old_and_new_folders_of_a_pair_are_one_column(site) -> None:
    assert site.pair_of("codex-glm", "zai-org/GLM-5.3") == site.pair_of("codex", "baseten/zai-org/GLM-5.3") == 0
    assert site.pair_of("mini-swe-agent", "baseten/zai-org/GLM-5.3") == 1
    assert len(site.HM) == 2  # no derived pair was appended


def test_a_rerun_pair_counts_only_its_new_condition(site) -> None:
    old = _trial(
        site, "a__codex-glm__1", "codex-glm", "zai-org/GLM-5.3", "a", "2026-09-27", image_input=False, solved=True
    )
    new = _trial(site, "a__codex__2", "codex", "baseten/zai-org/GLM-5.3", "a", "2026-09-30", image_input=True)
    new_infra = _trial(
        site, "b__codex__3", "codex", "baseten/zai-org/GLM-5.3", "b", "2026-09-30", image_input=True, infra=True
    )
    old_b = _trial(
        site, "b__codex-glm__4", "codex-glm", "zai-org/GLM-5.3", "b", "2026-09-27", image_input=False, solved=True
    )
    only_old = _trial(
        site, "c__codex-glm__5", "codex-glm", "zai-org/GLM-5.3", "c", "2026-09-27", image_input=False, solved=True
    )
    chosen = site.pick([old, new, new_infra, old_b, only_old])
    assert new["counted"] and not old["counted"]  # the later trial of the new condition counts
    assert new_infra["counted"] and not old_b["counted"]  # an infrastructure failure, never the old condition's trial
    assert not only_old["counted"] and chosen.get((0, "c"), []) == []  # a task only the old condition ran: not run
    assert only_old["earlier_condition"] and site.earlier_reason(only_old) == "an earlier run without image input"


def test_budget_stops_are_labelled_with_their_budget(site) -> None:
    t = _trial(
        site,
        "d__codex__6",
        "codex",
        "baseten/zai-org/GLM-5.3",
        "d",
        "2026-09-30",
        image_input=True,
        budget={"cap_usd": 5.0, "spent_usd": 5.1},
        outcome="budget_stop",
    )
    assert site.status(t) == "budget" and site.ST_RANK["budget"] == site.ST_RANK["no"]
    assert site.budget_text(t) == "Stopped at the $5 budget"
    assert site.long_status(t, "budget") == "Stopped at the $5 budget, counted as not solved"
    assert site.result_note(t) == "Stopped at the $5 budget"


def test_no_image_input_columns_are_labelled(site) -> None:
    t = _trial(
        site, "e__mini-swe-agent__7", "mini-swe-agent", "baseten/zai-org/GLM-5.3", "e", "2026-09-30", image_input=False
    )
    site.pick([t])
    site.HM[1]["_noimg"] = True
    assert "no image input" in site.phtml(1) and "no image input" not in site.phtml(0)
    assert "no image input" in site.noimg_tag()
