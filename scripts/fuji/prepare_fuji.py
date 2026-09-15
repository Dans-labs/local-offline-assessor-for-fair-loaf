# ruff: noqa: INP001
import argparse
import ast
import io
import json
import re
import tarfile
from difflib import unified_diff
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

from pydantic import BaseModel, ConfigDict, Field

_CONSTANTS = {
    "helper.metadata_mapper": (
        "Mapper",
        ("MATURITY_LEVELS", "REFERENCE_METADATA_LIST", "REQUIRED_CORE_METADATA"),
    ),
    "helper.metadata_collector": ("MetadataOfferingMethods", ()),
}
_EXTERNAL_IMPORTS = {"datetime", "enum", "pprint", "typing", "six", "dateutil.parser"}


class Recipe(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repository: str
    commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    archive_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evaluators: tuple[str, ...] = Field(min_length=1)


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


def generate(archive: bytes, recipe: Recipe) -> dict[str, bytes]:
    """Build isolated modules and provenance from an exact upstream archive."""
    if sha256(archive).hexdigest() != recipe.archive_sha256:
        raise ValueError("Upstream archive digest differs from the recipe")
    namespace = "fair_offline_assessor._vendor.fuji.v" + recipe.version.replace(
        ".", "_"
    )
    outputs = {"__init__.py": b""}
    records = []
    patches: list[str] = []
    pending = {"evaluators." + name for name in recipe.evaluators}
    reviewed = pending | {"evaluators.fair_evaluator", "util"} | _CONSTANTS.keys()
    seen: set[str] = set()
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as bundle:
        members = {member.name.partition("/")[2]: member for member in bundle}

        def read(path: str) -> bytes:
            """Read source bytes without extracting archive paths or links."""
            member = members.get(path)
            if member is None or not member.isfile():
                raise ValueError(f"Missing upstream file: {path}")
            stream = bundle.extractfile(member)
            if stream is None:
                raise ValueError(f"Unreadable upstream file: {path}")
            content = stream.read()
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
            pending.update(dependencies(source) - seen)
            rewritten = re.sub(
                r"(?m)^(\s*from )fuji_server(?=[. ])", r"\g<1>" + namespace, source
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
    outputs["imports.patch"] = "".join(patches).encode()
    provenance = recipe.model_dump(mode="json") | {
        "license": "MIT",
        "constants": _CONSTANTS,
        "files": sorted(records, key=lambda item: item["path"]),
    }
    outputs["upstream.json"] = (json.dumps(provenance, indent=2) + "\n").encode()
    return outputs


def prepare(
    archive: Path, target: Path, declaration: dict[str, object], *, check: bool = False
) -> None:
    """Validate and stage generated files before replacing this version's directory."""
    recipe = Recipe.model_validate(declaration)
    if target.name != "v" + recipe.version.replace(".", "_") or target.is_symlink():
        raise ValueError("Target must be the matching version directory")
    outputs = generate(archive.read_bytes(), recipe)
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


def main() -> None:
    """Prepare F-UJI from a local, pinned archive; never download or activate it."""
    parser = argparse.ArgumentParser(description="Prepare selected F-UJI evaluators.")
    parser.add_argument("archive", type=Path, help="Pinned upstream tar.gz archive")
    parser.add_argument(
        "--recipe", type=Path, default=Path(__file__).with_name("3.5.1.json")
    )
    parser.add_argument("--check", action="store_true", help="Compare without writing")
    arguments = parser.parse_args()
    try:
        declaration = json.loads(arguments.recipe.read_bytes())
        recipe = Recipe.model_validate(declaration)
        root = (
            Path(__file__).resolve().parents[2]
            / "src/fair_offline_assessor/_vendor/fuji"
        )
        prepare(
            arguments.archive,
            root / ("v" + recipe.version.replace(".", "_")),
            declaration,
            check=arguments.check,
        )
    except (OSError, ValueError, tarfile.TarError, SyntaxError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
