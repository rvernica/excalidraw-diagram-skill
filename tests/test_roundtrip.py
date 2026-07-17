"""End-to-end: render a scene to a .excalidraw.png, then recover it.

This ties the two scripts together the way the skill's render-view-fix loop
does — the PNG that render_offline writes must re-open losslessly via
extract_scene, byte-for-byte with the original scene JSON.
"""

from __future__ import annotations

import json

import extract_scene as es
import render_offline as ro


def test_render_then_extract_is_byte_identical(sample_scene_file):
    original_text = sample_scene_file.read_text(encoding="utf-8")

    png_path = ro.render(sample_scene_file, output_path=None, scale=2)

    scene_json, scene = es.recover_scene(png_path.read_bytes())
    # The embedded payload is the exact source text render_offline read in.
    assert scene_json == original_text
    assert scene == json.loads(original_text)


def test_extract_pretty_matches_scene(sample_scene_file):
    png_path = ro.render(sample_scene_file, output_path=None, scale=1)
    scene = es.extract_scene(png_path)
    assert scene["type"] == "excalidraw"
    assert len(scene["elements"]) == len(json.loads(sample_scene_file.read_text())["elements"])
