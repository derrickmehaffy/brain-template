"""Where the harness lives."""
from __future__ import annotations

import os
from pathlib import Path


def harness_root() -> Path:
    """The folder that contains this `_meta/` (the template checkout or the brain)."""
    return Path(os.path.realpath(__file__)).parent.parent.parent
