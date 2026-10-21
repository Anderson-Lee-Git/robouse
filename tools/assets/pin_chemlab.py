#!/usr/bin/env python3
"""Write assets/chemlab/provenance.json: the ChemLab-Assets files the chemlab suite uses, pinned to one revision of the
Hugging Face dataset with a SHA-256 per file.

None of these files is stored in git or in the package (the models, contracts and data are CC BY-NC 4.0);
`robouse fetch-assets --chemlab` downloads them into ~/.cache/robouse/chemlab and checks each hash.

    python tools/assets/pin_chemlab.py [--dest /tmp/chemlab]   # downloads the files to hash them

Per instrument (src/robouse/backends/chemlab/instruments.py): its URDF, its meshes (OBJ and MTL; not the GLB, Blender,
texture or preview files), its contract, and the runtime's module and data files; plus the release's LICENSE,
LICENSE-ASSETS.md and CITATION.cff.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
from robouse.backends.chemlab.instruments import DATASET, INSTRUMENTS, RELEASE, RELEASE_FILES, REVISION  # noqa: E402

API = f"https://huggingface.co/api/datasets/{DATASET}/tree/{REVISION}"
RAW = f"https://huggingface.co/datasets/{DATASET}/resolve/{REVISION}"


def tree(folder: str) -> list[dict]:
    with urllib.request.urlopen(f"{API}/{urllib.parse.quote(folder)}?recursive=true", timeout=60) as r:
        return [f for f in json.load(r) if f["type"] == "file"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dest", type=Path, help="folder to download into (default: a temporary folder)")
    a = ap.parse_args()
    dest = a.dest or Path(tempfile.mkdtemp(prefix="chemlab-pin-"))
    paths: list[str] = list(RELEASE_FILES)
    instruments = {}
    for slug, inst in INSTRUMENTS.items():
        meshes = sorted(f["path"] for f in tree(f"{inst.path}/meshes") if f["path"].endswith((".obj", ".mtl")))
        paths += [inst.urdf, *meshes, *inst.files()]
        instruments[slug] = {
            "chem_id": inst.chem_id,
            "name": inst.name,
            "maker": inst.maker,
            "model": inst.model,
            "path": inst.path,
        }
    files = []
    for rel in dict.fromkeys(paths):  # in order, once each
        url = f"{RAW}/{urllib.parse.quote(rel)}"
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(url, timeout=120) as r:
            data = r.read()
        out.write_bytes(data)
        files.append({"path": rel, "url": url, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    manifest = {
        "dataset": f"https://huggingface.co/datasets/{DATASET}",
        "code": "https://github.com/mbzuai-nlp/ChemLab-Assets",
        "revision": REVISION,
        "release": RELEASE,
        "licence": "Models, contracts and data: CC BY-NC 4.0 (LICENSE-ASSETS.md; non-commercial use only). Code, "
        "including the runtimes under scripts/: MIT (LICENSE). Copyright (c) 2026 Zirui Song, Jiadong Zhang, Jiahao "
        "Zhang, Xiaosong Ma, Xiaojun Chang, Xiuying Chen.",
        "note": "The ChemLab-Assets files the chemlab suite uses. Not stored in git or in the package; `robouse "
        "fetch-assets --chemlab` downloads them into ~/.cache/robouse/chemlab. Written by tools/assets/pin_chemlab.py.",
        "instruments": instruments,
        "files": files,
    }
    target = REPO / "assets" / "chemlab" / "provenance.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    print(f"{len(files)} files, {sum(f['bytes'] for f in files) / 1e6:.1f} MB -> {target} (downloaded into {dest})")


if __name__ == "__main__":
    main()
