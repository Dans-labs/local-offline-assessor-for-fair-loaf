# ruff: noqa: INP001
"""Prepare pinned Champion resources with Python and Git, without running Ruby."""

import argparse
import io
import json
import re
import subprocess
import tarfile
from hashlib import sha256
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from typing import Literal
from urllib.request import urlopen

from extract_champion import extract_catalog, extract_references
from pydantic import Field, JsonValue

from fair_offline_assessor.models.v1 import Model


class TestPolicy(Model):
    principles: tuple[Literal["F", "A", "I", "R"], ...] = Field(min_length=1)
    requires: tuple[str, ...]
    support: Literal["offline", "conditional", "unsupported"]
    branches: tuple[str, ...]
    adaptations: tuple[str, ...]


class Policy(Model):
    reason_codes: tuple[str, ...]
    adaptations: tuple[str, ...]
    tests: dict[str, TestPolicy]


class Harvester(Model):
    version: str
    url: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    files: dict[str, str]


class Recipe(Model):
    version: str = Field(pattern=r"^\d+\.\d+\.\d+(?:\.post\d+)?$")
    repository: str
    commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    tests: tuple[str, ...] = Field(min_length=1)
    source_hashes: dict[str, str]
    harvester: Harvester
    policy: Policy


def git(source: Path, *arguments: str) -> bytes:
    """Read committed blobs; never use working-tree files or execute hooks."""
    try:
        return subprocess.check_output(  # noqa: S603
            ["git", "-C", str(source), *arguments],  # noqa: S607
            stderr=subprocess.PIPE,
            timeout=120,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        raise ValueError("Cannot read pinned Git source") from exc


def checked(content: bytes, digest: str, label: str) -> bytes:
    """Require the reviewed SHA-256 before interpreting an input."""
    if sha256(content).hexdigest() != digest:
        raise ValueError(f"Source hash mismatch: {label}")
    return content


def safe_path(name: str) -> None:
    """Reject absolute, parent, or noncanonical archive/source paths."""
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or str(path) != name or "\\" in name:
        raise ValueError(f"Unsafe path: {name}")


def tar_members(content: bytes, selected: set[str]) -> dict[str, bytes]:
    """Read selected regular members in memory; reject links and unsafe paths."""
    result = {}
    seen = set()
    with tarfile.open(fileobj=io.BytesIO(content), mode="r:*") as archive:
        for member in archive:
            safe_path(member.name)
            if member.name in seen or not (member.isfile() or member.isdir()):
                raise ValueError(f"Unsafe archive member: {member.name}")
            seen.add(member.name)
            if member.name in selected:
                if not member.isfile():
                    raise ValueError(f"Unsafe selected member: {member.name}")
                stream = archive.extractfile(member)
                if stream is None:
                    raise ValueError(f"Missing archive member: {member.name}")
                result[member.name] = stream.read()
    if set(result) != selected:
        raise ValueError(f"Missing archive members: {selected - result.keys()}")
    return result


def read_sources(source: Path, gem: Path, recipe: Recipe) -> dict[str, str]:
    """Verify inventory, exact blobs, helper digests and dependency versions."""
    expected = set(recipe.tests)
    if len(expected) != len(recipe.tests):
        raise ValueError("Duplicate selected test")
    listing = git(source, "ls-tree", "-r", recipe.commit, "app/tests").decode()
    actual = set()
    for line in listing.splitlines():
        header, path = line.split("\t", 1)
        if PurePosixPath(path).name.startswith("test_FM_"):
            if not re.fullmatch(
                r"app/tests/test_FM_\w+\.rb", path
            ) or not header.startswith(("100644 blob ", "100755 blob ")):
                raise ValueError(f"Unexpected test source: {path}")
            actual.add(path)
    if actual != expected:
        raise ValueError(f"Test inventory mismatch: {sorted(actual ^ expected)}")
    if set(recipe.source_hashes) != expected | {"VERSION", "Gemfile.lock", "LICENSE"}:
        raise ValueError("Source hash inventory mismatch")
    required_helpers = {
        "lib/utils.rb",
        "lib/common_queries.rb",
        "lib/harvester.rb",
        "lib/fair_champion_harvester/version.rb",
        "LICENSE.txt",
    }
    if set(recipe.harvester.files) != required_helpers:
        raise ValueError("Helper inventory mismatch")
    sources = {}
    for path, digest in recipe.source_hashes.items():
        safe_path(path)
        sources[path] = checked(
            git(source, "show", f"{recipe.commit}:{path}"), digest, path
        ).decode()
    archive = checked(gem.read_bytes(), recipe.harvester.sha256, "harvester gem")
    inner = tar_members(archive, {"data.tar.gz"})["data.tar.gz"]
    for path, data in tar_members(inner, required_helpers).items():
        sources[path] = checked(data, recipe.harvester.files[path], path).decode()
    check_versions(sources, recipe)
    return sources


def check_versions(sources: dict[str, str], recipe: Recipe) -> None:
    """Check each independent upstream version declaration."""
    version = recipe.harvester.version
    if sources["VERSION"].strip() != f"Release v{recipe.version}":
        raise ValueError("Core version mismatch")
    if re.findall(
        r"^    fair_champion_harvester \(([^)]+)\)$",
        sources["Gemfile.lock"],
        re.MULTILINE,
    ) != [version]:
        raise ValueError("Locked harvester version mismatch")
    if re.findall(
        r'^HARVESTER_VERSION = "Hvst-([^"\n]+)"\.freeze$',
        sources["lib/harvester.rb"],
        re.MULTILINE,
    ) != [version]:
        raise ValueError("Harvester version mismatch")
    if re.findall(
        r'^\s*VERSION = "([^"\n]+)"$',
        sources["lib/fair_champion_harvester/version.rb"],
        re.MULTILINE,
    ) != [version]:
        raise ValueError("Gem version mismatch")


def json_bytes(value: object) -> bytes:
    """Use stable UTF-8 JSON without dates or machine-specific paths."""
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()


def outputs(recipe: Recipe, sources: dict[str, str]) -> dict[Path, bytes]:
    """Build all artifacts before writing; provenance hashes describe inputs."""
    catalog = extract_catalog(sources, harvester_version=recipe.harvester.version)
    policies = recipe.policy.tests
    if {row["id"] for row in catalog} != set(policies):
        raise ValueError("Missing or unexpected offline policy")
    for row in catalog:
        policy = policies[str(row["id"])]
        row.update(principles=list(policy.principles), requires=list(policy.requires))
    artifacts = {
        "catalog.json": json_bytes(catalog),
        "references.json": json_bytes(extract_references(sources)),
        "offline-policy.json": json_bytes(recipe.policy.model_dump(mode="json")),
        "upstream.json": json_bytes(
            {
                "repository": recipe.repository,
                "commit": recipe.commit,
                "version": recipe.version,
                "source_hashes": recipe.source_hashes,
                "harvester": recipe.harvester.model_dump(mode="json"),
                "adaptations": list(recipe.policy.adaptations),
            }
        ),
    }
    source = {
        "repository": recipe.repository,
        "commit": recipe.commit,
        "version": recipe.version,
    }
    declarations = []
    bindings = [
        "# Generated by scripts/champion/prepare_champion.py; do not edit.\n",
        "from fair_offline_assessor.models import ResourceRef\n\n",
        "DEFINITIONS: tuple[ResourceRef, ...] = (\n",
    ]
    for name, content in artifacts.items():
        key = "tests" if name == "catalog.json" else name.removesuffix(".json")
        declarations.append(
            {
                "id": f"champion:{key}",
                "path": name,
                "kind": "reference",
                "format": "json",
                "source": {
                    "path": "app/tests",
                    "transform": "python-static-extraction",
                },
            }
        )
        digest = sha256(content).hexdigest()
        bindings.append(
            "    ResourceRef(\n"
            f'        id="champion:{key}",\n'
            f'        version="{recipe.version}",\n'
            '        kind="reference",\n'
            '        format="json",\n'
            f'        digest="{digest}",\n'
            "    ),\n"
        )
    bindings.append(")\n")
    artifacts["manifest.json"] = json_bytes(
        {
            "version": recipe.version,
            "license": "MIT",
            "source": source,
            "files": declarations,
        }
    )
    bundle = (
        Path("src/fair_offline_assessor/resources/assessors/champion") / recipe.version
    )
    result = {bundle / name: data for name, data in artifacts.items()}
    module = "v" + recipe.version.replace(".", "_")
    result[
        Path("src/fair_offline_assessor/assessors/champion") / module / "bindings.py"
    ] = "".join(bindings).encode()
    result[Path("LICENSES/FAIR-Core-Tests-MIT.txt")] = sources["LICENSE"].encode()
    result[Path("LICENSES/FAIR-Champion-Harvester-MIT.txt")] = sources[
        "LICENSE.txt"
    ].encode()
    return result


def prepare(
    root: Path,
    recipe: dict[str, JsonValue],
    *,
    source: Path | None = None,
    harvester_gem: Path | None = None,
    check: bool = False,
) -> None:
    """Generate a reviewed bundle; check mode needs local inputs and never writes."""
    config = Recipe.model_validate(recipe)
    if check and (source is None or harvester_gem is None):
        raise ValueError("Check requires local --source and --harvester-gem inputs")
    if source is None or harvester_gem is None:
        with TemporaryDirectory(prefix="champion-prepare-") as directory:
            cache = Path(directory)
            if source is None:
                source = cache / "source"
                git(cache, "init", "--bare", str(source))
                git(source, "fetch", "--depth=1", config.repository, config.commit)
            if harvester_gem is None:
                if not config.harvester.url.startswith("https://"):
                    raise ValueError("Harvester download requires HTTPS")
                harvester_gem = cache / "harvester.gem"
                with urlopen(config.harvester.url, timeout=60) as response:  # noqa: S310
                    harvester_gem.write_bytes(response.read())
            prepare(root, recipe, source=source, harvester_gem=harvester_gem)
        return
    generated = outputs(config, read_sources(source, harvester_gem, config))
    for relative, content in generated.items():
        target = root / relative
        if check:
            if not target.is_file() or target.read_bytes() != content:
                raise ValueError(f"Stale generated file: {relative}")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)


def main() -> None:
    """Prepare or verify pinned Champion resources from upstream sources."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--recipe", type=Path, default=Path(__file__).with_name("0.5.12.json")
    )
    parser.add_argument("--source", type=Path)
    parser.add_argument("--harvester-gem", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        prepare(
            Path(__file__).resolve().parents[2],
            json.loads(args.recipe.read_bytes()),
            source=args.source,
            harvester_gem=args.harvester_gem,
            check=args.check,
        )
    except (ValueError, OSError, tarfile.TarError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
