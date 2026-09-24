import json
from copy import deepcopy
from functools import partial
from hashlib import sha256
from zipfile import ZipFile

import pytest
from pydantic import ValidationError

from fair_offline_assessor import (
    Assessor,
    assess,
    assessment,
    list_profiles,
    load_profile,
    profiles,
)
from fair_offline_assessor.assessors.champion.v0_5_12.adapter import ChampionAdapter
from fair_offline_assessor.models import (
    Profile,
    ProfileError,
    ProfileInfo,
    ResourceRecord,
)
from fair_offline_assessor.profiles import ProfileBundle


def profile_data():
    return {
        "schema_version": 1,
        "id": "example:metadata",
        "version": "1.0.0",
        "title": "Metadata checks",
        "adapter": "example",
        "engine_requires": ">=0.1,<0.2",
        "adapter_version": "1.0.0",
        "resources": [],
    }


@pytest.mark.parametrize(
    "problem",
    [
        "schema",
        "version",
        "requirement",
        "adapter",
        "duplicate_resource",
        "metrics",
    ],
)
def test_profile_model_rejects_invalid_definitions(problem):
    data = profile_data()
    assert Profile.model_validate(data).version == "1.0.0"
    match problem:
        case "schema":
            data["schema_version"] = 2
        case "version":
            data["version"] = "latest"
        case "requirement":
            data["engine_requires"] = "anything"
        case "adapter":
            data["adapter"] = ""
        case "duplicate_resource":
            data["resources"] = [{"id": "reference", "version": "1"}] * 2
        case "metrics":
            data["metrics"] = []
    with pytest.raises(ValidationError) as error:
        Profile.model_validate(data)
    if problem == "duplicate_resource":
        assert "Duplicate resource identifier" in str(error.value)


class MemoryProvider:
    def __init__(self, *profiles, resources=None, references=()):
        self.profiles = [json.dumps(data).encode() for data in profiles]
        self.resources = resources or {}
        self.references = references

    def list_profiles(self):
        return tuple(
            ProfileInfo(
                **{
                    key: json.loads(content)[key]
                    for key in (
                        "id",
                        "version",
                        "title",
                        "engine_requires",
                        "adapter",
                        "adapter_version",
                    )
                },
                digest=sha256(content).hexdigest(),
            )
            for content in self.profiles
        )

    def load(self, profile_id, version):
        content = next(
            content
            for content in self.profiles
            if (json.loads(content)["id"], json.loads(content)["version"])
            == (profile_id, version)
        )
        return ProfileBundle(content, self.resources, self.references)


def test_champion_version_selection_retains_existing_instances(monkeypatch):
    loaded = load_profile("fair-champion-offline@0.5.12")
    first = loaded.profile.model_dump()
    second = first | {"version": "0.5.12.post1", "adapter_version": "2.0.0"}
    provider = MemoryProvider(
        first, second, resources=loaded.resources, references=loaded.references
    )

    class FutureAdapter(ChampionAdapter):
        version = "2.0.0"  # Synthetic configuration: reuse these rules for routing.

    monkeypatch.setattr(
        assessment, "_builtin_adapters", lambda: (ChampionAdapter(), FutureAdapter())
    )
    monkeypatch.setattr(
        assessment, "load_profile", partial(load_profile, provider=provider)
    )
    existing = Assessor("FAIR_CHAMPION")
    baseline = existing.assess(metadata={}).model_dump(exclude={"raw"})
    monkeypatch.setattr(
        assessment,
        "_DEFAULT_PROFILES",
        {"FAIR_CHAMPION": "fair-champion-offline@0.5.12.post1"},
    )
    for selected in ("0.5.12", "0.5.12.post1"):
        named = Assessor("FAIR_CHAMPION", version=selected).assess(metadata={})
        direct = assess(
            {"metadata": {}},
            profile=f"fair-champion-offline@{selected}",
            provider=provider,
        )
        assert named.model_dump(exclude={"raw"}) == direct.model_dump(exclude={"raw"})
        assert named.profile.version == selected
        adapter_version = "1.0.0" if selected == "0.5.12" else "2.0.0"
        assert named.profile.adapter_version == adapter_version
        assert f"PythonAdapter:{adapter_version}" in named.model_dump_json()
    assert (
        Assessor("FAIR_CHAMPION").assess(metadata={}).profile.version == "0.5.12.post1"
    )
    assert existing.assess(metadata={}).model_dump(exclude={"raw"}) == baseline


@pytest.mark.parametrize("profile_id", ["example:metadata", "fusji-offline"])
def test_exact_versions_select_the_requested_profile(profile_id):
    first = profile_data()
    first["id"] = profile_id
    second = deepcopy(first)
    second["version"] = "2.0.0"
    second["adapter_version"] = "2.0.0"
    reference = ResourceRecord(
        id="reference",
        version="1.0.0",
        kind="reference",
        digest=sha256(b"{}").hexdigest(),
        path="reference.json",
        license="MIT",
        source={"url": "https://example.org/reference"},
    )
    first["resources"] = [{"id": "reference", "version": "1.0.0"}]
    second["resources"] = [{"id": "reference", "version": "2.0.0"}]
    provider = MemoryProvider(
        first,
        second,
        resources={"reference": b"{}"},
        references=(reference, reference.model_copy(update={"version": "2.0.0"})),
    )
    assert len(list_profiles(provider=provider)) == 2
    for version in ("1.0.0", "2.0.0"):
        result = load_profile(f"{profile_id}@{version}", provider=provider)
        assert result.profile.version == version
        assert result.profile.adapter == "example"
        assert result.profile.adapter_version == version
        assert result.references[0].version == version


@pytest.mark.parametrize(
    ("problem", "code"),
    [
        ("version", "profile_not_found"),
        ("engine", "incompatible_engine"),
        ("definition", "invalid_profile"),
        ("conflict", "profile_conflict"),
        ("resource", "resource_integrity"),
        ("missing_resource", "resource_integrity"),
        ("selection", "invalid_selection"),
    ],
)
def test_loading_rejects_incompatible_or_corrupted_profiles(problem, code):
    data = profile_data()
    data["resources"] = [{"id": "reference", "version": "1"}]
    references = (
        ResourceRecord(
            id="reference",
            version="1",
            kind="reference",
            digest=sha256(b"{}").hexdigest(),
            path="example.json",
            license="MIT",
            source={"url": "https://example.org/reference"},
        ),
    )
    resources = {"reference": b"{}"}
    selection = "example:metadata@1.0.0"
    others = []
    match problem:
        case "version":
            selection = "example:metadata@9.0.0"
        case "engine":
            data["engine_requires"] = ">=99"
        case "definition":
            data["schema_version"] = 2
        case "conflict":
            other = deepcopy(data)
            other["title"] = "Different content with the same version"
            others.append(other)
        case "resource":
            resources["reference"] = b"changed"
        case "missing_resource":
            resources.clear()
        case "selection":
            selection = "example:metadata@latest"
    with pytest.raises(ProfileError) as error:
        load_profile(
            selection,
            provider=MemoryProvider(
                data, *others, resources=resources, references=references
            ),
        )
    assert error.value.code == code


@pytest.mark.parametrize("storage", ["directory", "zip"])
def test_packaged_profiles_use_the_same_validation(tmp_path, monkeypatch, storage):
    data = profile_data()
    digest = sha256(b"{}").hexdigest()
    data["resources"] = [{"id": "reference", "version": "1"}]
    second = deepcopy(data)
    second["version"] = "2.0.0"
    xml = b"<schema/>"
    xml_digest = sha256(xml).hexdigest()
    second["resources"] = [{"id": "schema", "version": "1"}]
    references = (
        ResourceRecord(
            id="reference",
            version="1",
            kind="reference",
            digest=digest,
            path="reference.json",
            license="MIT",
            source={"url": "https://example.org/ref"},
        ),
        ResourceRecord(
            id="schema",
            version="1",
            kind="reference",
            digest=xml_digest,
            format="xml",
            path="schema.xml",
            license="MIT",
            source={"url": "https://example.org/schema"},
        ),
    )
    memory = MemoryProvider(
        data,
        second,
        resources={"reference": b"{}", "schema": xml},
        references=references,
    )
    package = f"example_profiles_{storage}"
    root = tmp_path / package / "resources"
    (root / "profiles").mkdir(parents=True)
    (root.parent / "__init__.py").touch()
    catalogue = memory.list_profiles()
    (root / "profiles.json").write_text(
        json.dumps([info.model_dump() for info in catalogue])
    )
    for info, content in zip(catalogue, memory.profiles, strict=True):
        path = root / "profiles" / info.id.replace(":", "/") / f"{info.version}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    (root / "resources.json").write_text(
        json.dumps([ref.model_dump() for ref in references])
    )
    (root / "reference.json").write_bytes(b"{}")
    (root / "schema.xml").write_bytes(xml)
    if storage == "zip":
        archive = tmp_path / "profiles.zip"
        with ZipFile(archive, "w") as bundle:
            for path in root.parent.rglob("*"):
                if path.is_file():
                    bundle.write(path, path.relative_to(tmp_path))
        monkeypatch.syspath_prepend(str(archive))
    else:
        monkeypatch.syspath_prepend(str(tmp_path))

    provider = profiles.BundledProfileProvider(package)
    assert profiles.list_profiles(provider=provider) == catalogue
    for version in ("1.0.0", "2.0.0"):
        selection = f"example:metadata@{version}"
        assert profiles.load_profile(
            selection, provider=provider
        ) == profiles.load_profile(selection, provider=memory)

    if storage == "directory":
        for path, code in (
            (root / "profiles.json", "invalid_catalogue"),
            (root / "profiles/example/metadata/1.0.0.json", "profile_integrity"),
            (root / "reference.json", "resource_integrity"),
        ):
            original = path.read_bytes()
            for replacement in (b"corrupted", None):
                if replacement is None:
                    path.unlink()
                else:
                    path.write_bytes(replacement)
                with pytest.raises(profiles.ProfileError) as error:
                    profiles.load_profile("example:metadata@1.0.0", provider=provider)
                assert error.value.code == code
            path.write_bytes(original)
