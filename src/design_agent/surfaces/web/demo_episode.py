"""The demo's episode: a plan written ahead of time and the labels it was read with, so the
demo's studio shows a whole episode without asking anything of a model or a classifier."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

#: `{"plan": ..., "labels": ...}`: what the demo's writer hands over, a stage at a turn.
SCRIPT: dict[str, Any] = json.loads(
    Path(__file__).with_name("demo_episode.json").read_text(encoding="utf8")
)
