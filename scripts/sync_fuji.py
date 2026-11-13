"""Synchronise one pinned F-UJI release from a verified upstream commit.

Usage:
    uv run python scripts/sync_fuji.py --check
    uv run python scripts/sync_fuji.py --source /path/to/fuji-git-checkout

The upstream extraction recipe is scripts/fuji/3.5.1.json. This command
intentionally refuses new versions until their integration recipe and
compatibility code have been reviewed; it does not silently transplant APIs.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "src" / "fair_offline_assessor"
RECIPE = ROOT / "scripts" / "fuji" / "3.5.1.json"


def validate_bundle() -> dict[str, object]:
    """Verify the shipped upstream snapshot and its recorded catalogue hashes."""
    recipe = json.loads(RECIPE.read_text())
    version = recipe["version"]
    package = PKG / "_vendor" / "fuji" / ("v" + version.replace(".", "_"))
    provenance = json.loads((package / "upstream.json").read_text())
    if provenance["commit"] != recipe["commit"] or provenance["version"] != version:
        raise ValueError("Vendored F-UJI revision does not match the pin")
    # Source file hashes in upstream.json are upstream provenance, before patches;
    # comparing them to patched code would give false positives. Instead verify the
    # complete, checked-in bundled resource index against actual resource bytes.
    index = json.loads((PKG / "resources" / "resources.json").read_text())
    count = 0
    for record in index:
        path = PKG / "resources" / record["path"]
        if not path.is_file() or sha256(path.read_bytes()).hexdigest() != record["digest"]:
            raise ValueError(f"Missing/modified packaged resource: {record['id']}")
        count += 1
    if not (package / "source.patch").is_file():
        raise ValueError("Missing offline adaptation patch")
    return {"version": version, "commit": provenance["commit"], "resources": count}


def run(command: list[str]) -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PKG.parent) + os.pathsep + env.get("PYTHONPATH", "")
    subprocess.run([sys.executable, *command], cwd=ROOT, env=env, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, help="Local F-UJI Git checkout containing the pinned commit")
    parser.add_argument("--check", action="store_true", help="Verify local bundle and generated index, without network access")
    args = parser.parse_args()
    if args.source and args.check:
        parser.error("--source and --check are mutually exclusive")
    if args.check:
        run(["scripts/resources/prepare_resources.py", "--check"])
    elif args.source:
        run(["scripts/fuji/prepare_fuji.py", "--recipe", str(RECIPE), "--source", str(args.source)])
        run(["scripts/resources/prepare_resources.py"])
    else:
        parser.error("Specify --check or --source; automatic unreviewed upstream upgrades are not supported")
    info = validate_bundle()
    print(f"F-UJI {info['version']} / {info['commit']}: {info['resources']} resources verified")


if __name__ == "__main__":
    main()
