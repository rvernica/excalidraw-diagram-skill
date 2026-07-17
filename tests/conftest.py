"""Shared fixtures. Puts ``references/`` on ``sys.path`` so the skill's
PEP 723 scripts import as plain modules (their script header is comment-only).
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

REFERENCES = Path(__file__).resolve().parent.parent / "references"
if str(REFERENCES) not in sys.path:
    sys.path.insert(0, str(REFERENCES))

# A scene exercising every element type the renderer handles, plus a deleted
# element (skipped) and an appState background.
SAMPLE_SCENE = {
    "type": "excalidraw",
    "version": 2,
    "source": "tests",
    "elements": [
        {
            "type": "rectangle",
            "id": "rect1",
            "x": 100,
            "y": 100,
            "width": 180,
            "height": 90,
            "strokeColor": "#1971c2",
            "backgroundColor": "#a5d8ff",
            "strokeWidth": 2,
            "strokeStyle": "solid",
            "roundness": {"type": 3},
        },
        {
            "type": "ellipse",
            "id": "ell1",
            "x": 320,
            "y": 100,
            "width": 120,
            "height": 120,
            "strokeColor": "#2f9e44",
            "backgroundColor": "transparent",
            "strokeWidth": 2,
            "strokeStyle": "dashed",
        },
        {
            "type": "diamond",
            "id": "dia1",
            "x": 100,
            "y": 240,
            "width": 140,
            "height": 100,
            "strokeColor": "#e8590c",
            "backgroundColor": "#ffd8a8",
            "strokeWidth": 1,
            "strokeStyle": "dotted",
        },
        {
            "type": "arrow",
            "id": "arr1",
            "x": 282,
            "y": 145,
            "width": 40,
            "height": 0,
            "strokeColor": "#1971c2",
            "backgroundColor": "transparent",
            "strokeWidth": 2,
            "points": [[0, 0], [40, 0]],
            "startArrowhead": None,
            "endArrowhead": "arrow",
        },
        {
            "type": "line",
            "id": "lin1",
            "x": 100,
            "y": 380,
            "width": 0,
            "height": 120,
            "strokeColor": "#495057",
            "backgroundColor": "transparent",
            "strokeWidth": 2,
            "points": [[0, 0], [0, 120]],
        },
        {
            "type": "text",
            "id": "txt1",
            "x": 130,
            "y": 132,
            "width": 120,
            "height": 25,
            "text": "Process\nstep",
            "fontSize": 16,
            "fontFamily": 3,
            "textAlign": "center",
            "verticalAlign": "middle",
            "strokeColor": "#1971c2",
            "lineHeight": 1.25,
        },
        {
            "type": "rectangle",
            "id": "gone",
            "x": -9999,
            "y": -9999,
            "width": 50,
            "height": 50,
            "strokeColor": "#000000",
            "isDeleted": True,
        },
    ],
    "appState": {"viewBackgroundColor": "#f8f9fa"},
}


@pytest.fixture
def sample_scene() -> dict:
    """A fresh deep copy of the sample scene (safe to mutate per test)."""
    return copy.deepcopy(SAMPLE_SCENE)


@pytest.fixture
def sample_scene_file(tmp_path: Path, sample_scene: dict) -> Path:
    """The sample scene written to a ``.excalidraw`` file."""
    path = tmp_path / "sample.excalidraw"
    path.write_text(json.dumps(sample_scene), encoding="utf-8")
    return path
