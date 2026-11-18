"""The shared matcher vectors, read from the installed package."""

import json
from importlib import resources
from typing import Any


def load_matcher_vectors() -> dict[str, Any]:
    """Return the parsed ``evidence/data/matcher_vectors.json``.

    The file ships inside the package, so this works from an installed wheel as
    well as from a checkout.
    """
    text = resources.files("evidence").joinpath("data/matcher_vectors.json").read_text("utf-8")
    return json.loads(text)
