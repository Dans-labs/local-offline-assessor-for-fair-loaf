# ruff: noqa: INP001
import argparse
import json
import re
from hashlib import sha256
from pathlib import Path
from typing import Literal

from pydantic import Field, TypeAdapter

from fair_offline_assessor.models import (
    Profile,
    ProfileInfo,
    ResourceRecord,
)
from fair_offline_assessor.models.v1 import Model, ResourcePath


class FileDeclaration(Model):
    id: str
    path: ResourcePath
    kind: Literal["context", "mapping", "reference"]
    format: Literal["json", "xml", "yaml"]
    source: dict[str, str] = Field(default_factory=dict)
    license: str | None = None
    aliases: tuple[str, ...] = ()


class BundleDeclaration(Model):
    version: str
    license: str
    source: dict[str, str]
    files: tuple[FileDeclaration, ...]


def read_local(root: Path, path: Path) -> bytes:
    """Read a bundled file without following links outside the resource tree."""
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Resource escapes its directory: {path}")
    return path.read_bytes()


def collect_resources(root: Path) -> tuple[ResourceRecord, ...]:
    """Combine bundle provenance with checksums of the supplied upstream files."""
    resources: dict[tuple[str, str], ResourceRecord] = {}
    manifests = sorted(
        path
        for category in ("metadata", "assessors")
        for path in (root / category).rglob("manifest.json")
    )
    for path in manifests:
        bundle = BundleDeclaration.model_validate_json(read_local(root, path))
        for file in bundle.files:
            source = bundle.source | file.source
            if not source.get("url") and not all(
                source.get(key) for key in ("repository", "commit", "path")
            ):
                raise ValueError(f"Missing upstream source: {file.id}")
            if source.get("repository") and not re.fullmatch(
                r"[0-9a-f]{40}|[0-9a-f]{64}", source.get("commit", "")
            ):
                raise ValueError(f"Use a full upstream commit: {file.id}")
            target = path.parent / file.path
            record = ResourceRecord(
                id=file.id,
                version=bundle.version,
                kind=file.kind,
                format=file.format,
                path=target.relative_to(root).as_posix(),
                digest=sha256(read_local(root, target)).hexdigest(),
                license=file.license or bundle.license,
                source=source,
                aliases=file.aliases,
            )
            key = (record.id, record.version)
            if key in resources:
                raise ValueError(f"Duplicate resource: {key}")
            resources[key] = record
    return tuple(resources[key] for key in sorted(resources))


def collect_profiles(
    root: Path, resources: tuple[ResourceRecord, ...]
) -> tuple[ProfileInfo, ...]:
    """Validate profile selections and derive their discovery catalogue."""
    available = {(resource.id, resource.version) for resource in resources}
    profiles: dict[tuple[str, str], ProfileInfo] = {}
    for path in sorted((root / "profiles").rglob("*.json")):
        content = read_local(root, path)
        profile = Profile.model_validate_json(content)
        expected = (
            root / "profiles" / profile.id.replace(":", "/") / f"{profile.version}.json"
        )
        if path != expected:
            raise ValueError(f"Profile belongs at {expected}")
        for resource in profile.resources:
            if (resource.id, resource.version) not in available:
                raise ValueError(f"Missing resource: {resource.id}@{resource.version}")
        info = ProfileInfo(
            **profile.model_dump(include=set(ProfileInfo.model_fields) - {"digest"}),
            digest=sha256(content).hexdigest(),
        )
        key = (info.id, info.version)
        if key in profiles:
            raise ValueError(f"Duplicate profile: {key}")
        profiles[key] = info
    return tuple(profiles[key] for key in sorted(profiles))


def check_released(
    root: Path,
    released: Path,
    profiles: tuple[ProfileInfo, ...],
    resources: tuple[ResourceRecord, ...],
) -> None:
    """Keep every released profile, resource and model schema unchanged."""
    for name, adapter, current in (
        ("profiles", TypeAdapter(tuple[ProfileInfo, ...]), profiles),
        ("resources", TypeAdapter(tuple[ResourceRecord, ...]), resources),
    ):
        previous = adapter.validate_json((released / f"{name}.json").read_bytes())
        indexed = {(item.id, item.version): item for item in current}
        for item in previous:
            if indexed.get((item.id, item.version)) != item:
                raise ValueError(f"Released {name} changed: {item.id}@{item.version}")
    for path in (released / "schemas").glob("*.json"):
        target = root / "schemas" / path.name
        if not target.is_file() or target.read_bytes() != path.read_bytes():
            raise ValueError(f"Released schema changed: {path.name}")


def prepare(root: Path, *, check: bool = False, released: Path | None = None) -> None:
    """Generate indexes, or check them without writing or accessing the network."""
    resources = collect_resources(root)
    profiles = collect_profiles(root, resources)
    if released is not None:
        check_released(root, released, profiles, resources)
    outputs = {
        root / f"{name}.json": (
            json.dumps([item.model_dump(mode="json") for item in items], indent=2)
            + "\n"
        ).encode()
        for name, items in (("resources", resources), ("profiles", profiles))
    }
    if check:
        for path, content in outputs.items():
            if not path.is_file() or path.read_bytes() != content:
                raise ValueError(f"Stale generated index: {path}")
    else:
        for path, content in outputs.items():
            path.write_bytes(content)


def main() -> None:
    """Prepare bundled resources from maintained declarations and local files."""
    parser = argparse.ArgumentParser(
        description="Generate indexes from local resource bundles."
    )
    parser.add_argument(
        "--check", action="store_true", help="Verify indexes without writing"
    )
    parser.add_argument(
        "--released",
        type=Path,
        help="Resource directory extracted from the previous release",
    )
    arguments = parser.parse_args()
    root = Path(__file__).resolve().parents[2] / "src/fair_offline_assessor/resources"
    try:
        prepare(root, check=arguments.check, released=arguments.released)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
