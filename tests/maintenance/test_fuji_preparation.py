import json
import runpy
import subprocess
from pathlib import Path

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
    files = {
        "fuji_server/evaluators/example.py": (
            "from fuji_server.models.example import Example\n" + extra
        ),
        "fuji_server/models/example.py": "class Example: pass\n",
        "LICENSE": "MIT example\n",
    }
    for name, content in files.items():
        path = repository / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    recipe = {
        "repository": str(repository),
        "commit": commit(repository),
        "version": "3.5.1",
        "evaluators": ["example"],
    }
    return repository, recipe


def test_preparation_follows_model_imports_and_checks_without_writing(tmp_path):
    prepare = runpy.run_path(str(SCRIPT))["prepare"]
    repository, recipe = source(tmp_path)
    (repository / "fuji_server/models/example.py").write_text(
        "class NewVersion: pass\n"
    )
    commit(repository)
    (repository / "fuji_server/models/example.py").write_text("uncommitted edit\n")
    target = tmp_path / "v3_5_1"
    prepare(target, recipe)
    model = target / "models/example.py"
    assert model.read_text() == "class Example: pass\n"
    assert (
        "fair_offline_assessor._vendor.fuji.v3_5_1.models.example"
        in (target / "evaluators/example.py").read_text()
    )
    assert len(json.loads((target / "upstream.json").read_bytes())["files"]) == 3
    prepare(target, recipe, check=True)
    model.write_text("edited\n")
    with pytest.raises(ValueError, match="Stale"):
        prepare(target, recipe, check=True)
    assert model.read_text() == "edited\n"
    (target / "obsolete.py").touch()
    prepare(target, recipe)
    assert not (target / "obsolete.py").exists()
    assert model.read_text() == "class Example: pass\n"


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
    _, recipe = source(tmp_path, extra=extra.get(problem, ""))
    if problem == "missing_commit":
        recipe["commit"] = "0" * 40
    target = tmp_path / "v3_5_1"
    target.mkdir()
    sentinel = target / "sentinel"
    sentinel.write_text("keep")
    with pytest.raises(ValueError, match=r"Git|Unreviewed"):
        prepare(target, recipe)
    assert list(target.iterdir()) == [sentinel]
    assert sentinel.read_text() == "keep"


def test_local_source_replaces_remote_fetch_without_changing_provenance(tmp_path):
    prepare = runpy.run_path(str(SCRIPT))["prepare"]
    repository, recipe = source(tmp_path)
    recipe["repository"] = "https://example.invalid/fuji"
    target = tmp_path / "v3_5_1"
    prepare(target, recipe, source=repository)
    record = json.loads((target / "upstream.json").read_bytes())
    assert record["repository"] == recipe["repository"]
    assert record["commit"] == recipe["commit"]
    assert (target / "models/example.py").read_text() == "class Example: pass\n"
