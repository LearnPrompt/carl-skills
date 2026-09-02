"""Built-in profiles.

Profiles are data, not code.  Load them with
``importlib.resources.files("carl_file_organizer.profiles").joinpath("tiered.json")``
so they keep working from a wheel; never build a path from ``__file__``.
"""

from __future__ import annotations

BUILTIN_PROFILES = ("tiered", "simple")
