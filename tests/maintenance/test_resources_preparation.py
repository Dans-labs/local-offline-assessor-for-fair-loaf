import json
import runpy
from pathlib import Path
from shutil import copytree

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/resources/prepare_resources.py"


def bundle(root):
    directory = root / "metadata/example/1"
    directory.mkdir(parents=True)
    (directory / "context.jsonld").write_bytes(b"{}")
    manifest = {
        "version": "1",
        "license": "MIT",
        "source": {"url": "https://example.org/context"},
        "files": [
            {
                "id": "example:context",
                "path": "context.jsonld",
                "kind": "context",
                "format": "json",
            }
        ],
    }
    (directory / "manifest.json").write_text(json.dumps(manifest))
    profile = root / "profiles/example/metadata/1.0.0.json"
    profile.parent.mkdir(parents=True)
    profile.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "id": "example:metadata",
                "version": "1.0.0",
                "title": "Example",
                "adapter": "example",
                "adapter_version": "1.0.0",
                "engine_requires": ">=0.1,<0.2",
                "resources": [{"id": "example:context", "version": "1"}],
            }
        )
    )
    return directory


def test_generation_is_repeatable_and_check_does_not_write(tmp_path):
    prepare = runpy.run_path(str(SCRIPT))["prepare"]
    bundle(tmp_path)
    prepare(tmp_path)
    index = tmp_path / "resources.json"
    original = index.read_bytes()
    resource = json.loads(original)[0]
    assert (
        resource["digest"]
        == "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
    )
    assert resource["path"] == "metadata/example/1/context.jsonld"
    prepare(tmp_path, check=True)
    index.write_text("[]")
    with pytest.raises(ValueError, match="Stale"):
        prepare(tmp_path, check=True)
    assert index.read_text() == "[]"
    prepare(tmp_path)
    assert index.read_bytes() == original


@pytest.mark.parametrize(
    "problem",
    ["changed_resource", "changed_profile", "missing_version", "traversal", "unpinned"],
)
def test_preparation_rejects_broken_or_changed_released_resources(tmp_path, problem):
    prepare = runpy.run_path(str(SCRIPT))["prepare"]
    root = tmp_path / "current"
    directory = bundle(root)
    prepare(root)
    released = tmp_path / "released"
    copytree(root, released)
    match problem:
        case "changed_resource":
            (directory / "context.jsonld").write_text('{"changed": true}')
        case "changed_profile":
            profile = root / "profiles/example/metadata/1.0.0.json"
            profile.write_text(profile.read_text().replace('"Example"', '"Changed"'))
        case "missing_version":
            (directory / "manifest.json").unlink()
        case "traversal":
            manifest = directory / "manifest.json"
            manifest.write_text(
                manifest.read_text().replace('"context.jsonld"', '"../outside.json"')
            )
        case "unpinned":
            manifest = directory / "manifest.json"
            data = json.loads(manifest.read_text())
            data["source"] = {
                "repository": "https://example.org/repo",
                "commit": "main",
                "path": "context.jsonld",
            }
            manifest.write_text(json.dumps(data))
    before = (root / "resources.json").read_bytes()
    with pytest.raises(
        ValueError, match=r"Released|Missing resource|relative resource|commit"
    ):
        prepare(root, released=None if problem == "unpinned" else released)
    assert (root / "resources.json").read_bytes() == before
