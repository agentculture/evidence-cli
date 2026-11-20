"""The shared vectors, read from the installed package.

``matcher_vectors.json`` holds the quote matcher's and the hand-back checker's
cases; ``strict_vectors.json`` holds the strict re-check's cases. Each is a
byte-identical copy of the file of the same name in associate's
``associate/contract/``, so other packages' tests can load the same cases.
"""

import json
from importlib import resources
from typing import Any


def _load(name: str) -> dict[str, Any]:
    text = resources.files("evidence").joinpath(f"data/{name}").read_text("utf-8")
    return json.loads(text)


def load_matcher_vectors() -> dict[str, Any]:
    """Return the parsed ``evidence/data/matcher_vectors.json``.

    The file ships inside the package, so this works from an installed wheel as
    well as from a checkout.
    """
    return _load("matcher_vectors.json")


def load_strict_vectors() -> dict[str, Any]:
    """Return the parsed ``evidence/data/strict_vectors.json``.

    Top-level keys: ``version``, ``redaction`` (the contract's redaction filter,
    used on the printed command) and ``cases`` (each with ``name``, ``note``,
    ``input`` and ``expect``). The rules behind the cases are written down in
    associate's ``docs/notes/strict-vectors.md``.
    """
    return _load("strict_vectors.json")
