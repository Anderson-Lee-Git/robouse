"""Install only audited upstream edits; reject unknown file content, never reset it."""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def install(name, root):
    root = Path(root).resolve()
    entry = json.loads((HERE / "sources.json").read_text())[name]
    patch = HERE / f"{name}-4.0.0.patch"
    if sha(patch) != entry["patch_sha256"]:
        raise ValueError("migration patch integrity failure")
    actual = {rel: sha(root / rel) for rel in entry["files"]}
    before = {rel: v["baseline"] for rel, v in entry["files"].items()}
    after = {rel: v["candidate"] for rel, v in entry["files"].items()}
    files = {
        p.relative_to(root).as_posix(): sha(p) for p in sorted(root.rglob("*.py")) if p.name != "macros_private.py"
    }
    tree = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if tree not in entry["python_tree_sha256"].values():
        raise ValueError(f"{name}: Python sources do not match the audited upstream snapshot")
    if (root / ".git").exists():
        revision = subprocess.check_output(
            ["git", "--no-optional-locks", "-C", str(root), "rev-parse", "HEAD"], text=True
        ).strip()
        if revision != entry["revision"]:
            raise ValueError(f"{name}: unexpected upstream revision")
    if actual == before:
        # Plain git apply changes files only, never the index or repository metadata.
        # GNU patch attempts an ownership change on its replacement temporary file,
        # which fails in restricted worktrees even when the target is writable.
        command = ["git", "--no-optional-locks", "-C", str(root), "apply"]
        subprocess.run([*command, "--check", str(patch)], check=True)
        subprocess.run([*command, str(patch)], check=True)
    elif actual != after:
        raise ValueError(f"{name}: unknown or partially patched sources; preserve them and use a fresh pinned checkout")
    if {rel: sha(root / rel) for rel in entry["files"]} != after:
        raise ValueError("patched source integrity failure")
    receipt = {
        "upstream_revision": entry["revision"],
        "patch_sha256": entry["patch_sha256"],
        "patched_files": after,
        "python_tree_sha256": entry["python_tree_sha256"]["candidate"],
        "engine": "4.0.0",
    }
    (root / "mujoco-migration-source.json").write_text(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--robocasa", required=True)
    parser.add_argument("--robosuite", required=True)
    args = parser.parse_args()
    install("robocasa", args.robocasa)
    install("robosuite", args.robosuite)
