"""Tests for references/render_offline.py."""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

import extract_scene as es
import render_offline as ro


# ---------- compute_bounding_box ----------


def test_bounding_box_of_shapes():
    els = [
        {"type": "rectangle", "x": 10, "y": 20, "width": 100, "height": 50},
        {"type": "ellipse", "x": 200, "y": 30, "width": 40, "height": 40},
    ]
    assert ro.compute_bounding_box(els) == (10, 20, 240, 70)


def test_bounding_box_uses_arrow_points():
    els = [{"type": "arrow", "x": 100, "y": 100, "points": [[0, 0], [50, -30]]}]
    assert ro.compute_bounding_box(els) == (100, 70, 150, 100)


def test_bounding_box_skips_deleted():
    els = [
        {"type": "rectangle", "x": 0, "y": 0, "width": 10, "height": 10},
        {"type": "rectangle", "x": 999, "y": 999, "width": 10, "height": 10, "isDeleted": True},
    ]
    assert ro.compute_bounding_box(els) == (0, 0, 10, 10)


def test_bounding_box_empty_returns_default():
    assert ro.compute_bounding_box([]) == (0, 0, 800, 600)


# ---------- stroke / transform attrs ----------


def test_stroke_attrs_transparent_background_becomes_none():
    attrs = ro._stroke_attrs({"backgroundColor": "transparent", "strokeColor": "#111"})
    assert 'fill="none"' in attrs
    assert 'stroke="#111"' in attrs


def test_stroke_attrs_dashed_and_opacity():
    attrs = ro._stroke_attrs({"strokeStyle": "dashed", "strokeWidth": 2, "opacity": 50})
    assert "stroke-dasharray" in attrs
    assert 'opacity="0.5"' in attrs


def test_transform_only_when_rotated():
    assert ro._transform({"angle": 0}) == ""
    rotated = ro._transform({"angle": 1.5708, "x": 0, "y": 0, "width": 100, "height": 100})
    assert "rotate(" in rotated


# ---------- per-element SVG emission ----------


def test_render_rectangle_rounded():
    svg = ro.render_rectangle({"x": 1, "y": 2, "width": 10, "height": 20, "roundness": {"type": 3}})
    assert svg.startswith("<rect")
    assert 'rx="10"' in svg


def test_render_rectangle_square_corners():
    svg = ro.render_rectangle({"x": 0, "y": 0, "width": 10, "height": 10})
    assert 'rx="0"' in svg


def test_render_ellipse():
    svg = ro.render_ellipse({"x": 0, "y": 0, "width": 100, "height": 50})
    assert svg.startswith("<ellipse")
    assert 'cx="50.0"' in svg and 'cy="25.0"' in svg
    assert 'rx="50.0"' in svg and 'ry="25.0"' in svg


def test_render_diamond_polygon_points():
    svg = ro.render_diamond({"x": 0, "y": 0, "width": 100, "height": 100})
    assert svg.startswith("<polygon")
    assert "50.0,0" in svg  # top vertex


def test_render_arrow_has_arrowhead():
    svg = ro.render_line(
        {"x": 0, "y": 0, "points": [[0, 0], [100, 0]], "endArrowhead": "arrow"},
        is_arrow=True,
    )
    assert "<polyline" in svg
    assert svg.count("<polygon") == 1  # one arrowhead


def test_render_arrow_both_ends():
    svg = ro.render_line(
        {
            "x": 0,
            "y": 0,
            "points": [[0, 0], [50, 0], [100, 0]],
            "startArrowhead": "arrow",
            "endArrowhead": "arrow",
        },
        is_arrow=True,
    )
    assert svg.count("<polygon") == 2


def test_render_line_no_fill():
    svg = ro.render_line(
        {"x": 0, "y": 0, "points": [[0, 0], [0, 100]], "backgroundColor": "#ff0000"}
    )
    assert 'fill="none"' in svg


def test_render_text_multiline_tspans():
    svg = ro.render_text(
        {"x": 0, "y": 0, "width": 100, "height": 40, "text": "one\ntwo", "fontSize": 16}
    )
    assert svg.startswith("<text")
    assert svg.count("<tspan") == 2
    assert ">one<" in svg and ">two<" in svg


def test_render_text_escapes_markup():
    svg = ro.render_text({"x": 0, "y": 0, "text": "a < b & c"})
    assert "&lt;" in svg and "&amp;" in svg


def test_render_element_dispatch():
    assert ro.render_element({"type": "rectangle"}).startswith("<rect")
    assert ro.render_element({"type": "ellipse"}).startswith("<ellipse")
    assert ro.render_element({"type": "diamond"}).startswith("<polygon")
    assert "<polyline" in ro.render_element({"type": "arrow", "points": [[0, 0], [1, 1]]})
    assert ro.render_element({"type": "text", "text": "x"}).startswith("<text")


def test_render_element_unknown_type_is_comment():
    assert (
        ro.render_element({"type": "frobnicate"}) == "<!-- unsupported element type: frobnicate -->"
    )


# ---------- build_svg ----------


def test_build_svg_dimensions_and_background(sample_scene):
    svg, w, h = ro.build_svg(sample_scene, padding=80)
    assert svg.startswith("<svg")
    assert f'width="{w}"' in svg
    assert 'fill="#f8f9fa"' in svg  # appState background
    assert w > 0 and h > 0


def test_build_svg_default_background_when_missing():
    svg, _, _ = ro.build_svg(
        {"elements": [{"type": "rectangle", "x": 0, "y": 0, "width": 10, "height": 10}]}
    )
    assert 'fill="#ffffff"' in svg


# ---------- validate ----------


def test_validate_accepts_good_scene(sample_scene):
    assert ro.validate(sample_scene) == []


def test_validate_wrong_type():
    errs = ro.validate({"type": "nope", "elements": [{}]})
    assert any("Expected type" in e for e in errs)


def test_validate_missing_elements():
    assert any("Missing 'elements'" in e for e in ro.validate({"type": "excalidraw"}))


def test_validate_elements_not_a_list():
    errs = ro.validate({"type": "excalidraw", "elements": {}})
    assert any("must be an array" in e for e in errs)


def test_validate_empty_elements():
    errs = ro.validate({"type": "excalidraw", "elements": []})
    assert any("is empty" in e for e in errs)


# ---------- embed_excalidraw_in_png ----------


def _minimal_png() -> bytes:
    from _helpers import build_png

    return build_png()


def test_embed_rejects_non_png(tmp_path):
    bad = tmp_path / "x.png"
    bad.write_bytes(b"definitely not a png")
    with pytest.raises(ValueError, match="not a PNG"):
        ro.embed_excalidraw_in_png(bad, "{}")


def test_embed_then_extract_round_trips(tmp_path, sample_scene):
    png = tmp_path / "d.png"
    png.write_bytes(_minimal_png())
    scene_json = json.dumps(sample_scene)
    ro.embed_excalidraw_in_png(png, scene_json)
    assert es.extract_scene(png) == sample_scene


def test_embed_strips_preexisting_text_chunks(tmp_path, sample_scene):
    # Start from a PNG that already carries a foreign text chunk.
    from _helpers import PNG_MAGIC, png_chunk

    out = bytearray(PNG_MAGIC)
    out += png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    out += png_chunk(b"tEXt", b"Software\x00excalidraw")
    out += png_chunk(b"IDAT", b"\x00")
    out += png_chunk(b"IEND", b"")
    png = tmp_path / "d.png"
    png.write_bytes(bytes(out))

    ro.embed_excalidraw_in_png(png, json.dumps(sample_scene))

    # Exactly one text chunk remains, and it's ours.
    text_chunks = [c for c, _ in es.iter_chunks(png.read_bytes()) if c == b"tEXt"]
    assert len(text_chunks) == 1
    assert es.extract_scene(png) == sample_scene


# ---------- render() end-to-end (needs cairosvg) ----------


def test_render_produces_valid_png_with_scene(sample_scene_file, sample_scene):
    out = ro.render(sample_scene_file, output_path=None, scale=1)
    assert out.exists()
    data = out.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    # Non-trivial dimensions from IHDR.
    width, height = struct.unpack(">II", data[16:24])
    assert width > 0 and height > 0
    # Scene survives the render and re-embed.
    assert es.extract_scene(out) == sample_scene


def test_render_default_output_path(sample_scene_file):
    out = ro.render(sample_scene_file, output_path=None, scale=1)
    assert out.name == "sample.excalidraw.png"


# ---------- CLI (main) ----------


def test_cli_missing_file_exits_1(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["render_offline.py", str(tmp_path / "nope.excalidraw")])
    with pytest.raises(SystemExit) as exc:
        ro.main()
    assert exc.value.code == 1
    assert "file not found" in capsys.readouterr().err


def test_cli_renders_and_prints_path(sample_scene_file, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["render_offline.py", str(sample_scene_file), "--scale", "1"])
    ro.main()
    printed = capsys.readouterr().out.strip()
    assert printed.endswith(".png")
    assert es.extract_scene(Path(printed)) == json.loads(sample_scene_file.read_text())
