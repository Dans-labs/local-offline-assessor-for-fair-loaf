from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from importlib.metadata import version as package_version
from importlib.resources import files
from typing import Protocol

from packaging.specifiers import SpecifierSet
from packaging.version import InvalidVersion, Version
from pydantic import TypeAdapter, ValidationError

from fair_offline_assessor.models import (
    Profile,
    ProfileError,
    ProfileInfo,
    ResourceRecord,
)


@dataclass(frozen=True)
class ProfileBundle:
    content: bytes
    resources: Mapping[str, bytes]
    references: tuple[ResourceRecord, ...]


@dataclass(frozen=True)
class LoadedProfile:
    profile: Profile
    info: ProfileInfo
    resources: Mapping[str, bytes]
    references: tuple[ResourceRecord, ...]


class ProfileProvider(Protocol):
    def list_profiles(self) -> tuple[ProfileInfo, ...]:
        """List available profile versions and their digests."""
        ...

    def load(self, profile_id: str, version: str) -> ProfileBundle:
        """Read an exact profile version and its resource bytes."""
        ...


def _read_profile(content: bytes, info: ProfileInfo) -> Profile:
    """Verify profile bytes against the catalogue before parsing."""
    if sha256(content).hexdigest() != info.digest:
        raise ProfileError(
            "profile_integrity", f"Profile digest differs: {info.id}@{info.version}"
        )
    try:
        return Profile.model_validate_json(content)
    except ValidationError as exc:
        raise ProfileError("invalid_profile", str(exc)) from exc


class BundledProfileProvider:
    def __init__(self, package: str = "fair_offline_assessor") -> None:
        """Use resources from the specified installed package."""
        self._root = files(package).joinpath("resources")

    def list_profiles(self) -> tuple[ProfileInfo, ...]:
        """Read and validate the packaged profile catalogue."""
        try:
            content = self._root.joinpath("profiles.json").read_bytes()
            return TypeAdapter(tuple[ProfileInfo, ...]).validate_json(content)
        except (OSError, ValidationError) as exc:
            raise ProfileError(
                "invalid_catalogue", "Cannot read profile catalogue"
            ) from exc

    def load(self, profile_id: str, version: str) -> ProfileBundle:
        """Read a pinned profile and its required resources."""
        info = next(
            (
                item
                for item in list_profiles(provider=self)
                if (item.id, item.version) == (profile_id, version)
            ),
            None,
        )
        if info is None:
            raise ProfileError(
                "profile_not_found", f"Profile not found: {profile_id}@{version}"
            )
        try:
            content = self._root.joinpath(
                "profiles", *info.id.split(":"), f"{info.version}.json"
            ).read_bytes()
        except OSError as exc:
            raise ProfileError("profile_integrity", "Missing profile file") from exc
        profile = _read_profile(content, info)
        try:
            references = TypeAdapter(tuple[ResourceRecord, ...]).validate_json(
                self._root.joinpath("resources.json").read_bytes()
            )
        except (OSError, ValidationError) as exc:
            raise ProfileError(
                "invalid_resources", "Cannot read resource index"
            ) from exc
        references = _select_resources(profile, references)
        resources = {}
        for reference in references:
            try:
                resources[reference.id] = self._root.joinpath(
                    *reference.path.split("/")
                ).read_bytes()
            except OSError as exc:
                raise ProfileError(
                    "resource_integrity", f"Missing resource: {reference.id}"
                ) from exc
        return ProfileBundle(content, resources, references)


def list_profiles(
    *, provider: ProfileProvider | None = None
) -> tuple[ProfileInfo, ...]:
    """List distinct profile versions, rejecting conflicting entries."""
    if provider is None:
        provider = BundledProfileProvider()
    profiles: dict[tuple[str, str], ProfileInfo] = {}
    for info in provider.list_profiles():
        key = (info.id, info.version)
        previous = profiles.get(key)
        if previous is not None and previous != info:
            raise ProfileError("profile_conflict", f"Conflicting profile: {key}")
        profiles[key] = info
    return tuple(profiles[key] for key in sorted(profiles))


def load_profile(
    selection: str, *, provider: ProfileProvider | None = None
) -> LoadedProfile:
    """Load ID@version and verify integrity and engine compatibility."""
    try:
        profile_id, selected_version = selection.rsplit("@", 1)
        normalized_version = str(Version(selected_version))
    except (ValueError, InvalidVersion) as exc:
        raise ProfileError(
            "invalid_selection", "Use an exact profile ID@version"
        ) from exc

    if not profile_id or normalized_version != selected_version:
        raise ProfileError("invalid_selection", "Use an exact profile ID@version")

    if provider is None:
        provider = BundledProfileProvider()
    info = next(
        (
            item
            for item in list_profiles(provider=provider)
            if (item.id, item.version) == (profile_id, selected_version)
        ),
        None,
    )
    if info is None:
        raise ProfileError("profile_not_found", f"Profile not found: {selection}")

    bundle = provider.load(profile_id, selected_version)
    profile = _read_profile(bundle.content, info)
    actual_info = ProfileInfo(
        id=profile.id,
        version=profile.version,
        title=profile.title,
        engine_requires=profile.engine_requires,
        adapter=profile.adapter,
        adapter_version=profile.adapter_version,
        digest=info.digest,
    )
    if actual_info != info:
        raise ProfileError(
            "profile_integrity", "Profile differs from its catalogue entry"
        )
    engine_version = package_version("fair-offline-assessor")
    if Version(engine_version) not in SpecifierSet(profile.engine_requires):
        raise ProfileError(
            "incompatible_engine",
            f"{selection} requires engine {profile.engine_requires}; "
            f"installed {engine_version}",
        )

    references = _select_resources(profile, bundle.references)
    resources = {}
    for reference in references:
        content = bundle.resources.get(reference.id)
        if content is None or sha256(content).hexdigest() != reference.digest:
            raise ProfileError(
                "resource_integrity", f"Missing or altered resource: {reference.id}"
            )
        resources[reference.id] = content
    return LoadedProfile(profile, info, resources, references)


def _select_resources(
    profile: Profile, references: tuple[ResourceRecord, ...]
) -> tuple[ResourceRecord, ...]:
    """Resolve exact resource versions and reject ambiguous index entries."""
    indexed = {}
    for reference in references:
        key = (reference.id, reference.version)
        if key in indexed:
            raise ProfileError("resource_conflict", f"Duplicate resource: {key}")
        indexed[key] = reference
    try:
        return tuple(indexed[(item.id, item.version)] for item in profile.resources)
    except KeyError as exc:
        raise ProfileError(
            "resource_integrity", f"Missing resource version: {exc}"
        ) from exc
