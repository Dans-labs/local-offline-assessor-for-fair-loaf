import json
import os
import runpy
import socket
import subprocess
import sys
from pathlib import Path
from shutil import copytree, ignore_patterns

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/fuji/prepare_fuji.py"


def git(repository, *arguments):
    return subprocess.check_output(  # noqa: S603
        ["git", "-C", str(repository), *arguments],  # noqa: S607
        text=True,
        timeout=10,
    ).strip()


def commit(repository):
    git(repository, "add", ".")
    git(
        repository,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.org",
        "commit",
        "--quiet",
        "-m",
        "test",
    )
    return git(repository, "rev-parse", "HEAD")


def source(tmp_path, *, extra=""):
    repository = tmp_path / "upstream"
    repository.mkdir()
    git(repository, "init", "--quiet")
    git(repository, "config", "core.autocrlf", "false")
    files = {
        "fuji_server/evaluators/example.py": (
            "from fuji_server.models.example import Example\n" + extra
        ),
        "fuji_server/models/example.py": "class Example: pass\n",
        "fuji_server/data/reference.yaml": "name: example\r\n",
        "LICENSE": "MIT example\n",
    }
    for name, content in files.items():
        path = repository / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode())
    recipe = {
        "repository": str(repository),
        "commit": commit(repository),
        "version": "3.5.1",
        "evaluators": ["example"],
    }
    resources = tmp_path / "resources/3.5.1"
    resources.mkdir(parents=True)
    manifest = {
        "version": "3.5.1",
        "license": "MIT",
        "source": {key: recipe[key] for key in ("repository", "commit")},
        "files": [
            {
                "id": "fuji:example",
                "path": "nested/reference.yaml",
                "kind": "reference",
                "format": "yaml",
                "source": {"path": "fuji_server/data/reference.yaml"},
            }
        ],
    }
    (resources / "manifest.json").write_text(json.dumps(manifest))
    return repository, recipe, resources


@pytest.mark.parametrize("timeout", [1, 2])
def test_data_link_preparation_removes_only_the_reviewed_timeout(tmp_path, timeout):
    prepare = runpy.run_path(str(SCRIPT))["prepare"]
    repository, recipe, resources = source(tmp_path)
    name = "fair_evaluator_data_identifier_included"
    (repository / f"fuji_server/evaluators/{name}.py").write_text(
        "import socket\n\nclass Evaluator:\n    def evaluate(self):\n"
        f"        socket.setdefaulttimeout({timeout})\n        return 7\n"
    )
    recipe.update(commit=commit(repository), evaluators=[name])
    manifest = resources / "manifest.json"
    declaration = json.loads(manifest.read_bytes())
    declaration["source"]["commit"] = recipe["commit"]
    manifest.write_text(json.dumps(declaration))
    target = tmp_path / "v3_5_1"
    if timeout != 1:
        with pytest.raises(ValueError, match="Missing reviewed"):
            prepare(target, recipe, resources=resources)
        assert not target.exists()
        return
    prepare(target, recipe, resources=resources)
    previous = socket.getdefaulttimeout()
    evaluator = runpy.run_path(str(target / f"evaluators/{name}.py"))["Evaluator"]
    assert evaluator().evaluate() == 7
    assert socket.getdefaulttimeout() == previous


@pytest.mark.parametrize("changed", ["code", "resource"])
def test_preparation_copies_pinned_files_and_checks_without_writing(tmp_path, changed):
    prepare = runpy.run_path(str(SCRIPT))["prepare"]
    repository, recipe, resources = source(tmp_path)
    (repository / "fuji_server/models/example.py").write_text(
        "class NewVersion: pass\n"
    )
    (repository / "fuji_server/data/reference.yaml").write_text("new version\n")
    commit(repository)
    (repository / "fuji_server/models/example.py").write_text("uncommitted edit\n")
    (repository / "fuji_server/data/reference.yaml").write_text("uncommitted edit\n")
    target = tmp_path / "v3_5_1"
    manifest = (resources / "manifest.json").read_bytes()
    prepare(target, recipe, resources=resources)
    model = target / "models/example.py"
    reference = resources / "nested/reference.yaml"
    assert model.read_text() == "class Example: pass\n"
    assert reference.read_bytes() == b"name: example\r\n"
    assert (resources / "manifest.json").read_bytes() == manifest
    assert (
        "fair_offline_assessor._vendor.fuji.v3_5_1.models.example"
        in (target / "evaluators/example.py").read_text()
    )
    assert len(json.loads((target / "upstream.json").read_bytes())["files"]) == 3
    prepare(target, recipe, resources=resources, check=True)
    edited = model if changed == "code" else reference
    edited.write_text("edited\n")
    with pytest.raises(ValueError, match="Stale"):
        prepare(target, recipe, resources=resources, check=True)
    assert edited.read_text() == "edited\n"
    (target / "obsolete.py").touch()
    prepare(target, recipe, resources=resources)
    assert not (target / "obsolete.py").exists()
    assert model.read_text() == "class Example: pass\n"
    assert reference.read_bytes() == b"name: example\r\n"


@pytest.mark.parametrize(
    "problem", ["missing_commit", "network_import", "service_import"]
)
def test_invalid_source_leaves_existing_vendor_files_untouched(tmp_path, problem):
    prepare = runpy.run_path(str(SCRIPT))["prepare"]
    extra = {
        "network_import": "import socket\n",
        "service_import": (
            "from fuji_server.helper.request_helper import RequestHelper\n"
        ),
    }
    _, recipe, resources = source(tmp_path, extra=extra.get(problem, ""))
    if problem == "missing_commit":
        manifest = resources / "manifest.json"
        manifest.write_text(manifest.read_text().replace(recipe["commit"], "0" * 40))
        recipe["commit"] = "0" * 40
    target = tmp_path / "v3_5_1"
    target.mkdir()
    sentinel = target / "sentinel"
    sentinel.write_text("keep")
    with pytest.raises(ValueError, match=r"Git|Unreviewed"):
        prepare(target, recipe, resources=resources)
    assert list(target.iterdir()) == [sentinel]
    assert sentinel.read_text() == "keep"


def test_local_source_replaces_remote_fetch_without_changing_provenance(tmp_path):
    prepare = runpy.run_path(str(SCRIPT))["prepare"]
    repository, recipe, resources = source(tmp_path)
    recipe["repository"] = "https://example.invalid/fuji"
    manifest = resources / "manifest.json"
    declaration = json.loads(manifest.read_bytes())
    declaration["source"]["repository"] = recipe["repository"]
    manifest.write_text(json.dumps(declaration))
    target = tmp_path / "v3_5_1"
    prepare(target, recipe, resources=resources, source=repository)
    record = json.loads((target / "upstream.json").read_bytes())
    assert record["repository"] == recipe["repository"]
    assert record["commit"] == recipe["commit"]
    assert (target / "models/example.py").read_text() == "class Example: pass\n"
    assert (resources / "nested/reference.yaml").read_bytes() == b"name: example\r\n"


def test_command_can_recreate_missing_vendor_files(tmp_path):
    repository, recipe, resources = source(tmp_path)
    package = tmp_path / "src/fair_offline_assessor"
    copytree(
        SCRIPT.parents[2] / "src/fair_offline_assessor",
        package,
        ignore=ignore_patterns("_vendor", "resources", "__pycache__"),
    )
    copytree(resources, package / "resources/assessors/fuji/3.5.1")
    script = tmp_path / "scripts/fuji/prepare_fuji.py"
    script.parent.mkdir(parents=True)
    script.write_bytes(SCRIPT.read_bytes())
    script.with_name("3.5.1.json").write_text(json.dumps(recipe))
    subprocess.run(  # noqa: S603
        [sys.executable, str(script), "--source", str(repository)],
        env={**os.environ, "PYTHONPATH": str(package.parent)},
        check=True,
        timeout=30,
    )
    assert (package / "_vendor/fuji/v3_5_1/models/example.py").read_text() == (
        "class Example: pass\n"
    )
    assert (
        package / "resources/assessors/fuji/3.5.1/nested/reference.yaml"
    ).read_bytes() == (b"name: example\r\n")


@pytest.mark.parametrize(
    "problem",
    [
        "version",
        "commit",
        "override",
        "missing",
        "traversal",
        "manifest",
        "duplicate",
        "symlink",
        "manifest_link",
    ],
)
def test_invalid_resource_leaves_existing_files_untouched(tmp_path, problem):
    prepare = runpy.run_path(str(SCRIPT))["prepare"]
    _, recipe, resources = source(tmp_path)
    target = tmp_path / "v3_5_1"
    target.mkdir()
    (target / "sentinel").write_text("keep")
    manifest = resources / "manifest.json"
    declaration = json.loads(manifest.read_bytes())
    file = declaration["files"][0]
    match problem:
        case "version":
            declaration["version"] = "3.5.2"
        case "commit":
            declaration["source"]["commit"] = "0" * 40
        case "override":
            file["source"]["commit"] = "0" * 40
        case "missing":
            file["source"]["path"] = "fuji_server/data/missing.yaml"
        case "traversal":
            file["path"] = "../outside.yaml"
        case "manifest":
            file["path"] = "manifest.json"
        case "duplicate":
            declaration["files"].append(file.copy())
        case "symlink":
            outside = tmp_path / "outside"
            outside.mkdir()
            (outside / "reference.yaml").write_text("keep")
            (resources / "nested").symlink_to(outside, target_is_directory=True)
        case "manifest_link":
            file["path"] = "reference.yaml"
            (resources / "reference.yaml").symlink_to(manifest)
    manifest.write_text(json.dumps(declaration))
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    with pytest.raises(
        ValueError, match=r"version|source|upstream|relative|Conflicting|Symlink"
    ):
        prepare(target, recipe, resources=resources)
    after = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    assert after == before
