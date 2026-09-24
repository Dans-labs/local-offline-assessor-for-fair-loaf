# ruff: noqa: INP001
"""Read only reviewed Ruby literals; never execute upstream code."""

import re
from collections.abc import Mapping
from hashlib import sha256
from pathlib import PurePosixPath

from pydantic import JsonValue

_STRING = r"""(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')"""
_REGEX = r"(?:%r\{(?:[^{}]|\{[^{}]*\})*\}|/(?:\\.|[^/\\])*/)[imx]*"


def one(pattern: str, source: str) -> str:
    """Require exactly one selected expression, rather than guessing a default."""
    matches = re.findall(pattern, source, re.MULTILINE)
    if len(matches) != 1:
        raise ValueError(f"Expected one reviewed expression: {pattern}")
    return str(matches[0])


def literal(value: str) -> str:
    """Decode the simple single-line strings used in selected metadata fields."""
    if not re.fullmatch(_STRING, value) or re.search(r"#[{@$]", value) or "\\" in value:
        raise ValueError(f"Unsupported string expression: {value}")
    return value[1:-1]


def extract_catalog(
    sources: Mapping[str, str], *, harvester_version: str
) -> list[dict[str, JsonValue]]:
    """Extract selected descriptors, keeping upstream identifiers and versions."""
    rows: list[dict[str, JsonValue]] = []
    seen = set()
    for path, source in sorted(sources.items()):
        if not re.fullmatch(r"app/tests/test_FM_\w+\.rb", path):
            continue
        test_id = PurePosixPath(path).stem
        block = one(rf"^  def self\.{test_id}_meta\n([\s\S]*?)^  end$", source)
        row: dict[str, JsonValue] = {}
        for upstream, field in (
            ("testid", "id"),
            ("testname", "name"),
            ("metric", "metric"),
            ("indicators", "indicators"),
        ):
            row[field] = literal(one(rf"^\s+{upstream}: (.*),$", block))
        if row["id"] != test_id or test_id in seen:
            raise ValueError(f"Duplicate or mismatched test ID: {test_id}")
        seen.add(test_id)
        expression = one(r"^\s+testversion: (.*),$", block)
        version = re.fullmatch(
            r"HARVESTER_VERSION \+ ':' \+ '(Tst-[0-9.]+)'", expression
        )
        if version is None:
            raise ValueError(f"Unsupported test version: {expression}")
        row.update(
            test_version=f"Hvst-{harvester_version}:{version[1]}",
            source_path=path,
            source_digest=sha256(source.encode()).hexdigest(),
        )
        rows.append(row)
    return rows


def ruby_regex(value: str) -> str:
    """Retain regex syntax for reviewed translation; reject Ruby interpolation."""
    if not re.fullmatch(_REGEX, value) or re.search(r"#[{@$]", value):
        raise ValueError(f"Unsupported regex expression: {value}")
    return value


def _items(body: str, pattern: str) -> list[str]:
    """Consume a comma-separated literal list, rejecting leftover expressions."""
    items = []
    rest = body.strip()
    while rest:
        if rest.startswith("#"):
            rest = rest.partition("\n")[2].lstrip()
            continue
        match = re.match(pattern, rest)
        if match is None:
            raise ValueError(f"Unsupported selected expression: {rest[:80]}")
        items.append(match[0])
        rest = rest[match.end() :].lstrip()
        if rest.startswith(","):
            rest = rest[1:].lstrip()
        elif rest and not rest.startswith("#"):
            raise ValueError(f"Unsupported list separator: {rest[:80]}")
    return items


def _predicates(source: str, name: str) -> list[JsonValue]:
    body = one(rf"::{name} = \[([\s\S]*?)^    \]", source)
    return [literal(item) for item in _items(body, _STRING)]


def extract_references(sources: Mapping[str, str]) -> dict[str, JsonValue]:
    """Extract ordered patterns/predicates and selected static check values."""
    utils = sources["lib/utils.rb"]
    body = one(r"::GUID_TYPES = \{([\s\S]*?)\}\s*\n  end", utils)
    patterns: list[JsonValue] = []
    for item in _items(body, rf"{_STRING}\s*=>\s*{_REGEX}"):
        key, regex = item.split("=>", 1)
        patterns.append(
            {"type": literal(key.strip()), "ruby": ruby_regex(regex.strip())}
        )
    persistent = sources["app/tests/test_FM_F1_M_IdentPersistent.rb"]
    expression = one(r"^      if (\(guid =~ .*)$", persistent)
    regexes = re.findall(rf"guid =~ ({_REGEX})", expression)
    remaining = re.sub(rf"guid =~ ({_REGEX})", "MATCH", expression)
    if not regexes or not re.fullmatch(r"\(MATCH\)(?: or \(MATCH\))*", remaining):
        raise ValueError("Unsupported persistence pattern expression")
    vocab = sources["app/tests/test_FM_I2_M_FAIRVocabSyntax.rb"]
    accepted = re.findall(rf"^      when ({_REGEX})(?:\s+#.*)?$", vocab, re.MULTILINE)
    if len(accepted) != len(re.findall(r"^      when ", vocab, re.MULTILINE)):
        raise ValueError("Unsupported vocabulary pattern")
    licenses: dict[str, JsonValue] = {}
    for suffix in ("", "_strong"):
        source = sources[f"app/tests/test_FM_R1_1_M_StdLic{suffix}.rb"]
        words = one(r"^    queries = %w\[([\s\S]*?)^    \]", source).split()
        if any(not re.fullmatch(r"https?://[^\s\[\]{}]+", w) for w in words):
            raise ValueError("Unsupported license predicates")
        schema = re.findall(
            r"query = SPARQL.parse\('select \?o where \{\?s "
            r"<(https?://schema.org/license)> \?o\}'\)",
            source,
        )
        if set(schema) != {"http://schema.org/license", "https://schema.org/license"}:
            raise ValueError("Missing schema license queries")
        licenses["strong" if suffix else "weak"] = [*words, *schema]
    policy = sources["app/tests/test_FM_A2_M_MetaLong.rb"]
    return {
        "identifier_patterns": patterns,
        "self_identifier_predicates": _predicates(utils, "SELF_IDENTIFIER_PREDICATES"),
        "data_predicates": _predicates(utils, "DATA_PREDICATES"),
        "persistent_url_patterns": [ruby_regex(value) for value in regexes],
        "accepted_vocabulary_patterns": [ruby_regex(value) for value in accepted],
        "vocabulary_threshold": float(
            one(r"^    if count > 0 and success >= count \* ([0-9.]+)$", vocab)
        ),
        "license_predicates": licenses,
        "persistence_policy_predicate": one(
            r"query = SPARQL.parse\('select \?o where \{\?s <([^>]+)> \?o\}'\)", policy
        ),
        "outward_link_exclusion": ruby_regex(
            one(
                rf"^      next if predicate.to_s =~ ({_REGEX})(?:\s+#.*)?$",
                sources["app/tests/test_FM_I3_M_QualRef.rb"],
            )
        ),
    }
