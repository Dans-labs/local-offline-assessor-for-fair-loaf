import io
import json
import runpy
import tarfile
from hashlib import sha256
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/fuji/prepare_fuji.py"


def source(tmp_path, *, extra=""):
    archive = tmp_path / "fuji.tar.gz"
    files = {
        "fuji_server/evaluators/example.py": (
            "from fuji_server.models.example import Example\n" + extra
        ),
        "fuji_server/models/example.py": "class Example: pass\n",
        "LICENSE": "MIT example\n",
    }
    with tarfile.open(archive, "w:gz") as bundle:
        for name, content in files.items():
            info = tarfile.TarInfo("fuji/" + name)
            info.size = len(content.encode())
            bundle.addfile(info, io.BytesIO(content.encode()))
    recipe = {
        "repository": "https://github.com/pangaea-data-publisher/fuji",
        "commit": "a" * 40,
        "version": "3.5.1",
        "archive_sha256": sha256(archive.read_bytes()).hexdigest(),
        "evaluators": ["example"],
    }
    return archive, recipe


def test_preparation_follows_model_imports_and_checks_without_writing(tmp_path):
    prepare = runpy.run_path(str(SCRIPT))["prepare"]
    archive, recipe = source(tmp_path)
    target = tmp_path / "v3_5_1"
    prepare(archive, target, recipe)
    model = target / "models/example.py"
    assert model.read_text() == "class Example: pass\n"
    assert (
        "fair_offline_assessor._vendor.fuji.v3_5_1.models.example"
        in (target / "evaluators/example.py").read_text()
    )
    assert len(json.loads((target / "upstream.json").read_bytes())["files"]) == 3
    prepare(archive, target, recipe, check=True)
    model.write_text("edited\n")
    with pytest.raises(ValueError, match="Stale"):
        prepare(archive, target, recipe, check=True)
    assert model.read_text() == "edited\n"
    (target / "obsolete.py").touch()
    prepare(archive, target, recipe)
    assert not (target / "obsolete.py").exists()
    assert model.read_text() == "class Example: pass\n"


@pytest.mark.parametrize("problem", ["digest", "network_import", "service_import"])
def test_invalid_source_leaves_existing_vendor_files_untouched(tmp_path, problem):
    prepare = runpy.run_path(str(SCRIPT))["prepare"]
    extra = {
        "network_import": "import socket\n",
        "service_import": (
            "from fuji_server.helper.request_helper import RequestHelper\n"
        ),
    }
    archive, recipe = source(tmp_path, extra=extra.get(problem, ""))
    if problem == "digest":
        recipe["archive_sha256"] = "0" * 64
    target = tmp_path / "v3_5_1"
    target.mkdir()
    sentinel = target / "sentinel"
    sentinel.write_text("keep")
    with pytest.raises(ValueError, match=r"digest|Unreviewed"):
        prepare(archive, target, recipe)
    assert list(target.iterdir()) == [sentinel]
    assert sentinel.read_text() == "keep"
