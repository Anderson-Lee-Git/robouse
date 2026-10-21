"""ChemLab-Assets files for the chemlab suite, downloaded at run time: never stored in the repository or the package.

ChemLab-Assets (MBZUAI, release 1.3.0) publishes its instrument models, contracts and data under CC BY-NC 4.0, which
does not allow commercial use, and its code (the behaviour runtimes under scripts/) under the MIT licence. Robo Use
includes none of it. `robouse fetch-assets --chemlab` downloads the files the chemlab tasks use (each instrument's
URDF, meshes, contract and the data its runtime reads, the runtimes themselves and the release's licence files),
listed with their SHA-256 in assets/chemlab/provenance.json (packaged as robouse/assets_provenance/chemlab.json), from
one pinned revision of the Hugging Face dataset, into <cache>/chemlab. $ROBOUSE_CHEMLAB_ASSETS overrides the location.
The folder keeps the dataset's layout, which the runtimes rely on to find their data.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath

from ... import config
from ...lib.download import fetch as fetch_file
from ...lib.download import sha256_file

HERE = Path(__file__).resolve()
LICENCE_NOTE = (
    "ChemLab-Assets' models, contracts and data are licensed CC BY-NC 4.0 (non-commercial use only; "
    "https://creativecommons.org/licenses/by-nc/4.0/); its code, including the behaviour runtimes, is MIT. "
    "Robo Use does not include them: they are downloaded for you to use under those terms."
)


def manifest_path() -> Path:
    """The pinned file list: the packaged copy in an installed wheel, else the checkout's."""
    shipped = HERE.parents[2] / "assets_provenance" / "chemlab.json"
    if shipped.is_file():
        return shipped
    return HERE.parents[4] / "assets" / "chemlab" / "provenance.json"


def manifest() -> dict:
    return json.loads(manifest_path().read_text())


def root() -> Path:
    """Where the downloaded files are: $ROBOUSE_CHEMLAB_ASSETS, else <cache>/chemlab."""
    override = config.env("ROBOUSE_CHEMLAB_ASSETS")
    return Path(override) if override else config.cache_dir() / "chemlab"


def download_bytes() -> int:
    return sum(int(f.get("bytes", 0)) for f in manifest()["files"])


def missing(paths: list[str] | None = None) -> list[str]:
    """Manifest files (all, or those under the given dataset paths) that are not in the download folder."""
    base = root()
    files = [f["path"] for f in manifest()["files"]]
    if paths is not None:
        files = [f for f in files if any(f == p or f.startswith(p.rstrip("/") + "/") for p in paths)]
    return [f for f in files if not (base / f).is_file()]


def require(paths: list[str]) -> Path:
    """The download folder, after checking that every manifest file under `paths` is there."""
    gone = missing(paths)
    if gone:
        raise FileNotFoundError(
            f"ChemLab-Assets files not found in {root()} (e.g. {gone[0]}); run `robouse fetch-assets --chemlab` once "
            f"(about {download_bytes() / 1e6:.0f} MB). {LICENCE_NOTE}"
        )
    return root()


def verified(path: str) -> Path:
    """A downloaded file whose SHA-256 still matches the manifest (for code that is imported, the runtimes)."""
    entry = next((f for f in manifest()["files"] if f["path"] == path), None)
    if entry is None:
        raise KeyError(f"{path} is not in the ChemLab-Assets manifest")
    p = root() / path
    if not p.is_file():
        require([path])
    if sha256_file(p) != entry["sha256"]:
        raise RuntimeError(
            f"{p} does not match its pinned SHA-256; run `robouse fetch-assets --chemlab` to download it again"
        )
    return p


def _inside(dest: Path, rel: str) -> Path:
    """Where a manifest file goes: `rel` must be a relative path without `..`, so that it stays inside `dest`."""
    p = PurePosixPath(rel)
    if p.is_absolute() or ".." in p.parts:
        raise ValueError(f"the ChemLab-Assets manifest names a path outside the download folder: {rel!r}")
    return dest / p


def fetch(dest: Path | None = None, log: Callable[[str], object] = print) -> Path:
    """Download the manifest files that are missing or differ from their pinned hash (eight at a time: they are
    small, so the time goes into the requests). Every path is checked before the first download."""
    m = manifest()
    dest = Path(dest) if dest else root()
    files = [(f, _inside(dest, f["path"])) for f in m["files"]]
    log(LICENCE_NOTE)
    with ThreadPoolExecutor(max_workers=8) as pool:
        got = list(pool.map(lambda fp: fetch_file(fp[0]["url"], fp[1], fp[0]["sha256"], timeout=120), files))
    log(f"{sum(got)} file(s) downloaded; ChemLab-Assets {m['release']} (revision {m['revision'][:12]}) in {dest}")
    return dest
