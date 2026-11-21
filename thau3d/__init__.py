"""Thau3D — describe a place, get a building you can walk through."""

from __future__ import annotations

__version__ = "0.1.0"

from .build import Builder, BuildReport, build_file
from .spec import (  # noqa: F401  (re-exported for convenience)
    Building,
    Issue,
    SpecError,
    load_spec,
    validate,
)

__all__ = [
    "Builder",
    "BuildReport",
    "Building",
    "Issue",
    "SpecError",
    "build_file",
    "load_spec",
    "validate",
    "__version__",
]
