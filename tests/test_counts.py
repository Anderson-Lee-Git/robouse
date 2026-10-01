"""Every task and suite count in README.md and the suites page is the package's (tools/docs/counts.py): the numbers
cannot drift from what the wheel bundles. tools/docs/suites_reference.py writes them."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("robouse_doc_counts", ROOT / "tools" / "docs" / "counts.py")
assert _spec and _spec.loader
counts = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(counts)

ROW = re.compile(r"^\| `([\w-]+)` \| [^|]* \| (\d+) \|", re.M)


def _table(begin: str, end: str) -> dict[str, int]:
    text = (ROOT / "docs" / "suites.md").read_text(encoding="utf-8")
    block = text.split(begin, 1)[1].split(end, 1)[0]
    return {suite: int(n) for suite, n in ROW.findall(block)}


def test_readme_and_suites_page_say_the_package_counts() -> None:
    bundled = counts.bundled()
    assert len(bundled) >= 30 and all(n > 0 for n in bundled.values())
    assert counts.mismatches() == []
    assert counts.phrase(bundled) in (ROOT / "README.md").read_text(encoding="utf-8")


def test_the_suites_table_is_the_package() -> None:
    assert _table("<!-- suites-table -->", "<!-- /suites-table -->") == counts.bundled()


def test_hub_only_suites_are_listed_separately() -> None:
    hub = counts.hub_only()
    assert all(n > 0 for n in hub.values()) and not set(hub) & set(counts.bundled())
    assert _table("<!-- hub-only-table -->", "<!-- /hub-only-table -->") == hub
