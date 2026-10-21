"""The docs site build (tools/docs/build_docs.py) stops on a page whose meta description is over 155 characters, or a
page PAGES lists that the repository does not have, so a release whose pages break either rule cannot be published:
both are checked here, where CI runs."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = [
    pytest.mark.maintainer,
    pytest.mark.skipif(sys.version_info < (3, 12), reason="tools/docs/build_docs.py needs Python 3.12"),
]


def test_every_published_page_fits_the_site_build() -> None:
    spec = importlib.util.spec_from_file_location("robouse_build_docs", ROOT / "tools" / "docs" / "build_docs.py")
    assert spec and spec.loader
    build_docs = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = build_docs  # its dataclasses look their module up
    try:
        spec.loader.exec_module(build_docs)
    finally:
        sys.modules.pop(spec.name, None)
    too_long = {page[1]: len(page[4]) for page in build_docs.PAGES if len(page[4]) > 155}
    assert not too_long, too_long
    assert not [page[1] for page in build_docs.PAGES if not (ROOT / page[1]).is_file()]
