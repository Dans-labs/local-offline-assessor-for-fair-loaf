import io
import json
import runpy
import subprocess
import tarfile
from hashlib import sha256
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/champion/prepare_champion.py"
EXTRACT = ROOT / "scripts/champion/extract_champion.py"
# Independently transcribed from the pinned coverage audit, not the recipe.
IDS = (
    "test_FM_A1_1_M_OpenProt",
    "test_FM_A1_1_M_OpenProt_Data",
    "test_FM_A1_2_M_Auth",
    "test_FM_A1_2_M_DataAuth",
    "test_FM_A2_M_MetaLong",
    "test_FM_F1_M_IdentPersistent",
    "test_FM_F1_M_IdentUnique",
    "test_FM_F3_M_DataIdent",
    "test_FM_F3_M_MetaIdent",
    "test_FM_F4_M_MetaIndexed",
    "test_FM_I1_M_FormLangSemantic_Data",
    "test_FM_I1_M_FormalLangSyntax",
    "test_FM_I2_M_FAIRVocabSyntax",
    "test_FM_I3_M_QualRef",
    "test_FM_R1_1_M_StdLic",
    "test_FM_R1_1_M_StdLic_strong",
)


def git(repository, *args):
    return subprocess.check_output(  # noqa: S603
        ["git", "-C", str(repository), *args],  # noqa: S607
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
        "--allow-empty",
        "-m",
        "test",
    )
    return git(repository, "rev-parse", "HEAD")


def archive(files, *, bad=None):
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w:gz") as tar:
        for name, body in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(body.encode())
            tar.addfile(member, io.BytesIO(body.encode()))
        if bad:
            member = tarfile.TarInfo(bad)
            if bad == "link":
                member.type = tarfile.SYMTYPE
                member.linkname = "/outside"
            tar.addfile(member)
    return data.getvalue()


def gem_bytes(files, *, bad=None):
    inner = archive(files, bad=bad)
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w") as tar:
        member = tarfile.TarInfo("data.tar.gz")
        member.size = len(inner)
        tar.addfile(member, io.BytesIO(inner))
    return data.getvalue()


@pytest.fixture
def inputs(tmp_path):
    repo = tmp_path / "source"
    repo.mkdir()
    git(repo, "init", "--quiet")
    sources = json.loads(
        (ROOT / "tests/fixtures/champion/0.5.12/extraction.json").read_text()
    )
    core = {p: s for p, s in sources.items() if not p.startswith("lib/")}
    for name, text in core.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    helpers = {p: s for p, s in sources.items() if p.startswith("lib/")}
    helpers["LICENSE.txt"] = "Test MIT license\n"
    helpers["lib/fair_champion_harvester/version.rb"] = 'VERSION = "0.1.17"\n'
    gem = tmp_path / "harvester.gem"
    gem.write_bytes(gem_bytes(helpers))
    recipe = json.loads((ROOT / "scripts/champion/0.5.12.json").read_text())
    recipe.update(repository=str(repo), commit=commit(repo))
    recipe["source_hashes"] = {
        p: sha256(s.encode()).hexdigest() for p, s in core.items()
    }
    recipe["harvester"].update(
        sha256=sha256(gem.read_bytes()).hexdigest(),
        files={p: sha256(s.encode()).hexdigest() for p, s in helpers.items()},
    )
    return repo, gem, recipe, helpers


def preparer(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPT.parent))
    return runpy.run_path(str(SCRIPT))["prepare"]


def test_preparation_is_deterministic_and_uses_git_blobs(tmp_path, monkeypatch, inputs):
    prepare = preparer(monkeypatch)
    repo, gem, recipe, _ = inputs
    target = tmp_path / "out"
    prepare(target, recipe, source=repo, harvester_gem=gem)
    before = {
        p.relative_to(target): (p.read_bytes(), p.stat().st_mtime_ns)
        for p in target.rglob("*")
        if p.is_file()
    }
    (repo / "VERSION").write_text("dirty checkout ignored\n")
    prepare(target, recipe, source=repo, harvester_gem=gem, check=True)
    assert before == {
        p.relative_to(target): (p.read_bytes(), p.stat().st_mtime_ns)
        for p in target.rglob("*")
        if p.is_file()
    }
    prepare(target, recipe, source=repo, harvester_gem=gem)
    assert {p: data for p, (data, _) in before.items()} == {
        p.relative_to(target): p.read_bytes() for p in target.rglob("*") if p.is_file()
    }
    catalog = json.loads(
        (
            target
            / "src/fair_offline_assessor/resources/assessors/champion"
            / "0.5.12/catalog.json"
        ).read_text()
    )
    assert tuple(row["id"] for row in catalog) == IDS
    assert len({row["metric"] for row in catalog}) == 13
    assert all(row["test_version"].startswith("Hvst-0.1.17:Tst-") for row in catalog)
    assert not (target / "src/fair_offline_assessor/resources/profiles").exists()
    next(p for p in target.rglob("catalog.json")).write_text("[]")
    with pytest.raises(ValueError, match="Stale"):
        prepare(target, recipe, source=repo, harvester_gem=gem, check=True)


@pytest.mark.parametrize(
    "change",
    [
        "core-version",
        "gem-version",
        "gem-hash",
        "helper-hash",
        "helper-missing",
        "source-hash",
        "missing",
        "extra",
        "duplicate",
        "interpolation",
    ],
)
def test_preparation_rejects_unreviewed_sources(  # noqa: C901, PLR0912
    tmp_path, monkeypatch, inputs, change
):
    prepare = preparer(monkeypatch)
    repo, gem, recipe, helpers = inputs
    path = repo / f"app/tests/{IDS[0]}.rb"
    if change == "core-version":
        (repo / "VERSION").write_text("9.0\n")
    elif change == "gem-version":
        helpers["lib/harvester.rb"] = 'HARVESTER_VERSION = "Hvst-9.0".freeze\n'
    elif change == "gem-hash":
        recipe["harvester"]["sha256"] = "0" * 64
    elif change == "helper-hash":
        recipe["harvester"]["files"]["lib/utils.rb"] = "0" * 64
    elif change == "helper-missing":
        del helpers["lib/common_queries.rb"]
    elif change == "source-hash":
        recipe["source_hashes"]["VERSION"] = "0" * 64
    elif change == "missing":
        path.unlink()
    elif change == "extra":
        (repo / "app/tests/test_FM_extra.rb").write_text(path.read_text())
    elif change == "duplicate":
        recipe["tests"].append(recipe["tests"][0])
    elif change == "interpolation":
        path.write_text(
            path.read_text().replace("testname: '", 'testname: "#{unknown}')
        )
    if change in {"gem-version", "helper-missing"}:
        gem.write_bytes(gem_bytes(helpers))
        recipe["harvester"].update(sha256=sha256(gem.read_bytes()).hexdigest())
        if change == "gem-version":
            recipe["harvester"]["files"]["lib/harvester.rb"] = sha256(
                helpers["lib/harvester.rb"].encode()
            ).hexdigest()
    recipe["commit"] = commit(repo)
    if change in {"core-version", "interpolation"}:
        p = "VERSION" if change == "core-version" else f"app/tests/{IDS[0]}.rb"
        recipe["source_hashes"][p] = sha256((repo / p).read_bytes()).hexdigest()
    with pytest.raises(ValueError, match=r"mismatch|Missing|Duplicate|Unsupported"):
        prepare(tmp_path / "out", recipe, source=repo, harvester_gem=gem)
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("bad", ["../escape", "/absolute", "link"])
def test_archive_rejects_unsafe_members(tmp_path, monkeypatch, inputs, bad):
    prepare = preparer(monkeypatch)
    repo, gem, recipe, helpers = inputs
    gem.write_bytes(gem_bytes(helpers, bad=bad))
    recipe["harvester"]["sha256"] = sha256(gem.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="Unsafe"):
        prepare(tmp_path / "out", recipe, source=repo, harvester_gem=gem)
    assert not (tmp_path / "out").exists()


def test_check_requires_local_inputs_without_creating_outputs(tmp_path, monkeypatch):
    prepare = preparer(monkeypatch)
    recipe = json.loads((ROOT / "scripts/champion/0.5.12.json").read_text())
    with pytest.raises(ValueError, match="local"):
        prepare(tmp_path / "out", recipe, check=True)
    assert not (tmp_path / "out").exists()


def test_extraction_preserves_order_and_rejects_selected_expressions():
    api = runpy.run_path(str(EXTRACT))
    sources = json.loads(
        (ROOT / "tests/fixtures/champion/0.5.12/extraction.json").read_text()
    )
    refs = api["extract_references"](sources)
    assert [r["type"] for r in refs["identifier_patterns"]] == [
        "inchi",
        "doi",
        "handle1",
        "handle2",
        "uri",
        "purl",
        "ark_url",
        "ark",
    ]
    assert (
        refs["identifier_patterns"][1]["ruby"] == r"%r{^10.\d{4,9}/[-._;()/:A-Z0-9]+$}i"
    )
    assert refs["self_identifier_predicates"][:2] == [
        "http://purl.org/dc/elements/1.1/identifier",
        "https://purl.org/dc/elements/1.1/identifier",
    ]
    assert refs["vocabulary_threshold"] == 0.66
    sources["lib/utils.rb"] = sources["lib/utils.rb"].replace(
        '"http://www.w3.org/ns/ldp#contains"', 'ENV.fetch("PREDICATE")'
    )
    with pytest.raises(ValueError, match="Unsupported"):
        api["extract_references"](sources)


@pytest.mark.parametrize(
    ("source_path", "original", "replacement"),
    [
        ("lib/utils.rb", r"/purl\./", r"/#{expression}/"),
        ("app/tests/test_FM_I3_M_QualRef.rb", "%r{1999/xhtml}", "%r{#{expression}}"),
    ],
)
def test_regex_interpolation_is_not_silently_treated_as_a_literal(
    source_path, original, replacement
):
    api = runpy.run_path(str(EXTRACT))
    sources = json.loads(
        (ROOT / "tests/fixtures/champion/0.5.12/extraction.json").read_text()
    )
    sources[source_path] = sources[source_path].replace(original, replacement)
    with pytest.raises(ValueError, match="Unsupported"):
        api["extract_references"](sources)
