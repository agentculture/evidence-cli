"""docs/library.md lists the public library names; every one must import.

The table rows have the form ``| `module` | `name` | what it is |``. A name in the
table that cannot be imported, or one of the eight names associate imports that is
missing from the table, fails here.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

LIBRARY_DOC = Path(__file__).resolve().parent.parent / "docs" / "library.md"
ROW = re.compile(r"^\|\s*`([A-Za-z0-9_.]+)`\s*\|\s*`([A-Za-z0-9_]+)`\s*\|", re.MULTILINE)
ASSOCIATE_IMPORTS = {
    "check_quote",
    "parse_source_ref",
    "check_handback",
    "load_export",
    "load_handback_input",
    "inspect_export",
    "accuracy_result",
    "fact_counts",
}


def _listed() -> list[tuple[str, str]]:
    return ROW.findall(LIBRARY_DOC.read_text(encoding="utf-8"))


def test_library_doc_lists_names() -> None:
    assert len(_listed()) >= len(ASSOCIATE_IMPORTS)


def test_every_listed_name_imports() -> None:
    for module_name, name in _listed():
        module = importlib.import_module(module_name)
        assert hasattr(module, name), f"{module_name}.{name} is listed but does not exist"


def test_the_eight_names_associate_imports_are_listed() -> None:
    listed = {name for _, name in _listed()}
    assert ASSOCIATE_IMPORTS <= listed


def test_no_name_is_listed_twice() -> None:
    listed = _listed()
    assert len(listed) == len(set(listed))


def test_callables_listed_as_functions_are_callable() -> None:
    for name in ASSOCIATE_IMPORTS:
        module_name = next(m for m, n in _listed() if n == name)
        assert callable(getattr(importlib.import_module(module_name), name))


#: The names associate is expected to import for the strict re-check (docs/library.md).
STRICT_ASSOCIATE_IMPORTS = {
    "strict_recheck",
    "load_strict_vectors",
    "is_strict_export",
    "recheck_strict_export",
}
STRICT_ROW = re.compile(
    r"^\|\s*`([A-Za-z0-9_.]+)`\s*\|\s*`([A-Za-z0-9_]+)`\s*\|[^|]*\|\s*(yes|no)\s*\|\s*$",
    re.MULTILINE,
)


def test_the_strict_names_associate_imports_are_listed_as_used_and_callable() -> None:
    used = {name: flag for _, name, flag in STRICT_ROW.findall(LIBRARY_DOC.read_text("utf-8"))}
    for name in STRICT_ASSOCIATE_IMPORTS:
        assert used.get(name) == "yes", name
        module_name = next(m for m, n in _listed() if n == name)
        assert callable(getattr(importlib.import_module(module_name), name))


def test_the_library_doc_says_which_strict_names_associate_imports() -> None:
    text = " ".join(LIBRARY_DOC.read_text("utf-8").split())
    assert (
        "associate is expected to import the four names marked in the last column for strict"
        in text
    )
