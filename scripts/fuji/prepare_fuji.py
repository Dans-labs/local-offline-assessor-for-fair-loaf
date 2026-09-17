# ruff: noqa: INP001
import argparse
import ast
import json
import os
import re
import subprocess
from difflib import unified_diff
from hashlib import sha256
from pathlib import Path
from shutil import which
from tempfile import TemporaryDirectory

from pydantic import BaseModel, ConfigDict, Field

_CONSTANTS = {
    "helper.metadata_mapper": (
        "Mapper",
        (
            "MATURITY_LEVELS",
            "PROVENANCE_MAPPING",
            "REFERENCE_METADATA_LIST",
            "REQUIRED_CORE_METADATA",
        ),
    ),
    "helper.metadata_collector": ("MetadataOfferingMethods", ()),
}
_EXTERNAL_IMPORTS = {
    "datetime",
    "enum",
    "pprint",
    "typing",
    "urllib.parse",
    "six",
    "dateutil.parser",
    "fnmatch",
    "re",
    "idutils",
    "Levenshtein",
    "hashid",
    "uuid",
}
# Version-scoped edits keep service and network behaviour out of copied helpers.
_REPLACEMENTS = {
    ("3.5.1", "evaluators.fair_evaluator_data_identifier_included"): (
        ("import socket\n", "", 1),
        ("        socket.setdefaulttimeout(1)\n", "", 1),
    ),
    ("3.5.1", "evaluators.fair_evaluator_unique_identifier_metadata"): (
        (
            "IdentifierHelper(self.fuji.id)",
            (
                "IdentifierHelper(self.fuji.id, "
                "identifiers_org_data=self.fuji.IDENTIFIERS_ORG_DATA)"
            ),
            3,
        ),
    ),
    ("3.5.1", "evaluators.fair_evaluator_related_resources"): (
        (
            'IdentifierHelper(relation.get("related_resource"))',
            (
                'IdentifierHelper(relation.get("related_resource"), '
                "identifiers_org_data=self.fuji.IDENTIFIERS_ORG_DATA)"
            ),
            1,
        ),
    ),
    ("3.5.1", "helper.identifier_helper"): (
        ("import urllib\n", "import urllib.parse\n", 1),
        ("from fuji_server.helper.preprocessor import Preprocessor\n", "", 1),
        (
            (
                "from fuji_server.helper.request_helper import "
                "AcceptTypes, RequestHelper\n"
            ),
            "",
            1,
        ),
        ("    IDENTIFIERS_ORG_DATA = Preprocessor.get_identifiers_org_data()\n", "", 1),
        (
            "    def __init__(self, idstring, logger=None):\n",
            (
                "    def __init__(self, idstring, logger=None, *, "
                "identifiers_org_data):\n"
                "        self.IDENTIFIERS_ORG_DATA = identifiers_org_data\n"
            ),
            1,
        ),
    ),
}
_REMOVED_METHODS = {
    ("3.5.1", "helper.identifier_helper"): (
        "IdentifierHelper.get_resolved_url",
        "IdentifierHelper.get_identifier_info",
    ),
}


class Recipe(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repository: str
    commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    evaluators: tuple[str, ...] = Field(min_length=1)


def git(repository: Path, *arguments: str) -> bytes:
    """Run Git without interactive prompts."""
    executable = which("git")
    if executable is None:
        raise ValueError("Git is required to prepare F-UJI")
    try:
        return subprocess.run(  # noqa: S603
            [executable, "-C", str(repository), *arguments],
            check=True,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=60,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        ).stdout
    except subprocess.CalledProcessError as exc:
        raise ValueError(
            f"Git failed: {exc.stderr.decode(errors='replace').strip()}"
        ) from exc


def read_source(repository: Path, commit: str, path: str) -> bytes:
    """Read a committed regular file without checkout filters or local edits."""
    entry = git(repository, "ls-tree", commit, "--", path)
    if entry.split(b" ", 1)[0] not in {b"100644", b"100755"}:
        raise ValueError(f"Missing upstream file: {path}")
    return git(repository, "cat-file", "blob", f"{commit}:{path}")


def resource_files(root: Path, recipe: Recipe) -> dict[str, str]:
    """Read resource paths from the manifest and verify their source pin."""
    manifest = json.loads((root / "manifest.json").read_bytes())
    if manifest["version"] != recipe.version:
        raise ValueError("Resource version differs from the recipe")
    files = {}
    for file in manifest["files"]:
        source = manifest["source"] | file.get("source", {})
        if any(
            source.get(key) != getattr(recipe, key) for key in ("repository", "commit")
        ):
            raise ValueError("Resource source differs from the recipe")
        name = file["path"]
        path = Path(name)
        if (
            not path.parts
            or path.is_absolute()
            or ".." in path.parts
            or path.as_posix() != name
            or any(character in name for character in ("\\", ":", "\x00"))
        ):
            raise ValueError(f"Use a relative resource path: {name}")
        if name == "manifest.json" or name in files:
            raise ValueError(f"Conflicting resource path: {name}")
        if (root / name).resolve() != root.resolve() / name:
            raise ValueError(f"Symlinked resource path: {name}")
        files[name] = source["path"]
    return files


def constants(source: str, module: str) -> str:
    """Extract the reviewed enum or enum members without importing collectors."""
    name, members = _CONSTANTS[module]
    classes = [
        node
        for node in ast.parse(source).body
        if isinstance(node, ast.ClassDef) and node.name == name
    ]
    if len(classes) != 1:
        raise ValueError(f"Missing upstream enum: {module}.{name}")
    selected: list[ast.AST] = [classes[0]]
    if members:
        selected = [
            node
            for node in classes[0].body
            if isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id in members
        ]
        if len(selected) != len(members):
            raise ValueError(f"Missing upstream constants: {module}.{name}")
    prefix = "".join(source.splitlines(keepends=True)[:4]) + "import enum\n\n\n"
    if members:
        prefix += f"class {name}(enum.Enum):\n"
    return (
        prefix
        + "\n\n".join(
            ("    " if members else "") + (ast.get_source_segment(source, node) or "")
            for node in selected
        )
        + "\n"
    )


def dependencies(source: str) -> set[str]:
    """Collect static imports and reject dependencies that have not been reviewed."""
    internal = set()
    for node in ast.walk(ast.parse(source)):
        names: list[str] = []
        if isinstance(node, ast.ImportFrom):
            if node.level or not node.module or any(n.name == "*" for n in node.names):
                raise ValueError("Unreviewed relative or wildcard import")
            names = (
                [f"fuji_server.{name.name}" for name in node.names]
                if node.module == "fuji_server"
                else [node.module]
            )
        elif isinstance(node, ast.Import):
            names = [name.name for name in node.names]
            if any(name.startswith("fuji_server") for name in names):
                raise ValueError("Unreviewed package import; expected from-import")
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"__import__", "eval", "exec"}
        ):
            raise ValueError(f"Unreviewed dynamic execution: {node.func.id}")
        for name in names:
            if name.startswith("fuji_server."):
                internal.add(name.removeprefix("fuji_server."))
            elif name not in _EXTERNAL_IMPORTS:
                raise ValueError(f"Unreviewed import: {name}")
    return internal


def offline_source(source: str, module: str, version: str) -> str:
    """Apply reviewed source edits and remove methods that perform resolution."""
    key = (version, module)
    methods = _REMOVED_METHODS.get(key, ())
    lines = source.splitlines(keepends=True)
    found = [
        node
        for cls in ast.parse(source).body
        if isinstance(cls, ast.ClassDef)
        for node in cls.body
        if isinstance(node, ast.FunctionDef) and f"{cls.name}.{node.name}" in methods
    ]
    if len(found) != len(methods):
        raise ValueError(f"Missing reviewed resolution methods in {module}")
    for node in reversed(found):
        del lines[node.lineno - 1 : node.end_lineno]
    source = "".join(lines)
    if methods:
        source = source.rstrip() + "\n"
    for old, new, count in _REPLACEMENTS.get(key, ()):
        if source.count(old) != count:
            raise ValueError(f"Missing reviewed source in {module}: {old.strip()}")
        source = source.replace(old, new)
    return source


def generate(repository: Path, recipe: Recipe) -> dict[str, bytes]:
    """Copy selected modules from the pinned Git commit."""
    namespace = "fair_offline_assessor._vendor.fuji.v" + recipe.version.replace(
        ".", "_"
    )
    outputs = {"__init__.py": b""}
    records = []
    patches: list[str] = []
    pending = {"evaluators." + name for name in recipe.evaluators}
    reviewed = pending | {"evaluators.fair_evaluator", "util"} | _CONSTANTS.keys()
    reviewed.update(
        module for version, module in _REPLACEMENTS if version == recipe.version
    )
    seen: set[str] = set()

    def read(path: str) -> bytes:
        """Record the original bytes used to generate vendor files."""
        content = read_source(repository, recipe.commit, path)
        records.append({"path": path, "sha256": sha256(content).hexdigest()})
        return content

    read("LICENSE")
    while pending:
        module = min(pending)
        pending.remove(module)
        if module in seen:
            continue
        if module not in reviewed and not re.fullmatch(r"models\.[a-z_]+", module):
            raise ValueError(f"Unreviewed F-UJI dependency: {module}")
        seen.add(module)
        path = module.replace(".", "/") + ".py"
        original = read("fuji_server/" + path).decode("utf-8")
        source = constants(original, module) if module in _CONSTANTS else original
        rewritten = offline_source(source, module, recipe.version)
        pending.update(dependencies(rewritten) - seen)
        rewritten = re.sub(
            r"(?m)^(\s*from )fuji_server(?=[. ])", r"\g<1>" + namespace, rewritten
        )
        compile(rewritten, path, "exec")
        outputs[path] = rewritten.encode()
        for parent in Path(path).parents:
            outputs[(parent / "__init__.py").as_posix()] = b""
        patches.extend(
            unified_diff(
                source.splitlines(keepends=True),
                rewritten.splitlines(keepends=True),
                fromfile="a/fuji_server/" + path,
                tofile="b/" + path,
            )
        )
    outputs["source.patch"] = "".join(patches).encode()
    provenance = recipe.model_dump(mode="json") | {
        "license": "MIT",
        "constants": _CONSTANTS,
        "files": sorted(records, key=lambda item: item["path"]),
    }
    outputs["upstream.json"] = (json.dumps(provenance, indent=2) + "\n").encode()
    return outputs


def prepare(
    target: Path,
    declaration: dict[str, object],
    *,
    resources: Path,
    check: bool = False,
    source: Path | None = None,
) -> None:
    """Fetch the pinned commit and prepare its files before replacing this version."""
    recipe = Recipe.model_validate(declaration)
    if target.name != "v" + recipe.version.replace(".", "_") or target.is_symlink():
        raise ValueError("Target must be the matching version directory")
    files = resource_files(resources, recipe)
    with TemporaryDirectory(prefix="fuji-source-") as temporary:
        repository = Path(temporary)
        git(repository, "init", "--bare", "--quiet")
        git(
            repository,
            "fetch",
            "--quiet",
            "--depth=1",
            "--no-tags",
            "--no-recurse-submodules",
            "--",
            str(source.resolve()) if source is not None else recipe.repository,
            recipe.commit,
        )
        if (
            git(repository, "rev-parse", "FETCH_HEAD^{commit}").decode().strip()
            != recipe.commit
        ):
            raise ValueError("Fetched Git commit differs from the recipe")
        outputs = generate(repository, recipe)
        references = {
            name: read_source(repository, recipe.commit, path)
            for name, path in files.items()
        }
    if check:
        current = {
            path.relative_to(target).as_posix(): path.read_bytes()
            for path in target.rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
        }
        changed = sorted(
            name
            for name in current.keys() | outputs.keys()
            if current.get(name) != outputs.get(name)
        )
        changed.extend(
            f"resources/{name}"
            for name, content in references.items()
            if not (resources / name).is_file()
            or (resources / name).read_bytes() != content
        )
        if changed:
            raise ValueError("Stale F-UJI files: " + ", ".join(changed))
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=target.parent, prefix=".prepare-fuji-") as temporary:
        staged = Path(temporary) / "generated"
        for name, content in outputs.items():
            path = staged / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        previous = Path(temporary) / "previous"
        if target.exists():
            target.rename(previous)
        try:
            staged.rename(target)
        except OSError:
            if previous.exists():
                previous.rename(target)
            raise
    for name, content in references.items():
        path = resources / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


def main() -> None:
    """Fetch and prepare the F-UJI version selected by a recipe."""
    parser = argparse.ArgumentParser(
        description="Prepare selected F-UJI evaluators and resources."
    )
    parser.add_argument("--source", type=Path, help="Use a local Git repository")
    parser.add_argument(
        "--recipe", type=Path, default=Path(__file__).with_name("3.5.1.json")
    )
    parser.add_argument("--check", action="store_true", help="Compare without writing")
    arguments = parser.parse_args()
    try:
        declaration = json.loads(arguments.recipe.read_bytes())
        recipe = Recipe.model_validate(declaration)
        root = Path(__file__).resolve().parents[2] / "src/fair_offline_assessor"
        prepare(
            root / "_vendor/fuji" / ("v" + recipe.version.replace(".", "_")),
            declaration,
            resources=root / "resources/assessors/fuji" / recipe.version,
            check=arguments.check,
            source=arguments.source,
        )
    except (OSError, ValueError, subprocess.TimeoutExpired, SyntaxError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
