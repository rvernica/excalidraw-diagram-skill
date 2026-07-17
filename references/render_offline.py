#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "cairosvg>=2.7.0",
# ]
# ///
"""Offline Excalidraw renderer: JSON -> SVG -> PNG, with scene re-embed.

No browser, no esm.sh, no Playwright. The output PNG carries the scene
JSON in a tEXt chunk so it can be re-opened in excalidraw.com.

Usage:
    ./render_offline.py <path-to-file.excalidraw> [--output path.png] [--scale 2]

The PEP 723 header above lets `uv run` resolve cairosvg into a cached
ephemeral environment on first invocation; nothing is installed
persistently into the user's project or system Python.

Handles the six element types the skill emits:
    rectangle, ellipse, diamond, arrow, line, text

Fidelity is pragmatic, not pixel-perfect vs. excalidraw.com. The PNG is
for the render-view-fix loop; the embedded scene JSON is canonical and
opens cleanly in excalidraw.com.
"""

from __future__ import annotations

import argparse
import json
import math
import struct
import sys
import xml.sax.saxutils as sax
import zlib
from pathlib import Path


# ---------- Bounding box ----------


def compute_bounding_box(elements: list[dict]) -> tuple[float, float, float, float]:
    min_x = float("inf")
    min_y = float("inf")
    max_x = float("-inf")
    max_y = float("-inf")
    for el in elements:
        if el.get("isDeleted"):
            continue
        x = el.get("x", 0)
        y = el.get("y", 0)
        w = el.get("width", 0)
        h = el.get("height", 0)
        if el.get("type") in ("arrow", "line") and "points" in el:
            for px, py in el["points"]:
                min_x = min(min_x, x + px)
                min_y = min(min_y, y + py)
                max_x = max(max_x, x + px)
                max_y = max(max_y, y + py)
        else:
            min_x = min(min_x, x)
            min_y = min(min_y, y)
            max_x = max(max_x, x + abs(w))
            max_y = max(max_y, y + abs(h))
    if min_x == float("inf"):
        return (0, 0, 800, 600)
    return (min_x, min_y, max_x, max_y)


# ---------- SVG emission ----------

FONT_FAMILY_MAP = {
    1: "Virgil, Segoe UI Emoji, sans-serif",
    2: "Helvetica, Arial, sans-serif",
    3: "Cascadia, Consolas, monospace",
    4: "Assistant, sans-serif",
}


def _attr(name: str, value) -> str:
    if value is None:
        return ""
    return f' {name}="{sax.escape(str(value), {chr(34): "&quot;"})}"'


def _stroke_attrs(el: dict) -> str:
    stroke = el.get("strokeColor") or "#000000"
    fill = el.get("backgroundColor") or "none"
    if fill in ("transparent", "", None):
        fill = "none"
    sw = el.get("strokeWidth", 1)
    style = el.get("strokeStyle", "solid")
    dash = None
    if style == "dashed":
        dash = f"{sw * 4},{sw * 3}"
    elif style == "dotted":
        dash = f"{sw},{sw * 2}"
    opacity = float(el.get("opacity", 100)) / 100.0
    return (
        _attr("stroke", stroke)
        + _attr("fill", fill)
        + _attr("stroke-width", sw)
        + _attr("stroke-dasharray", dash)
        + _attr("opacity", opacity)
        + ' stroke-linecap="round" stroke-linejoin="round"'
    )


def _transform(el: dict) -> str:
    angle = el.get("angle") or 0
    if not angle:
        return ""
    cx = el.get("x", 0) + el.get("width", 0) / 2
    cy = el.get("y", 0) + el.get("height", 0) / 2
    deg = angle * 180.0 / math.pi
    return f' transform="rotate({deg:.4f} {cx:.2f} {cy:.2f})"'


def render_rectangle(el: dict) -> str:
    x, y = el.get("x", 0), el.get("y", 0)
    w, h = el.get("width", 0), el.get("height", 0)
    rx = 10 if el.get("roundness") else 0
    return (
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" '
        f'rx="{rx}" ry="{rx}"{_stroke_attrs(el)}{_transform(el)} />'
    )


def render_ellipse(el: dict) -> str:
    x, y = el.get("x", 0), el.get("y", 0)
    w, h = el.get("width", 0), el.get("height", 0)
    cx, cy = x + w / 2, y + h / 2
    rx, ry = abs(w) / 2, abs(h) / 2
    return f'<ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry}"{_stroke_attrs(el)}{_transform(el)} />'


def render_diamond(el: dict) -> str:
    x, y = el.get("x", 0), el.get("y", 0)
    w, h = el.get("width", 0), el.get("height", 0)
    pts = f"{x + w / 2},{y} {x + w},{y + h / 2} {x + w / 2},{y + h} {x},{y + h / 2}"
    return f'<polygon points="{pts}"{_stroke_attrs(el)}{_transform(el)} />'


def _arrowhead(x1: float, y1: float, x2: float, y2: float, color: str, sw: float) -> str:
    angle = math.atan2(y2 - y1, x2 - x1)
    size = max(8, sw * 4)
    a1 = angle + math.radians(150)
    a2 = angle - math.radians(150)
    p1 = (x2 + size * math.cos(a1), y2 + size * math.sin(a1))
    p2 = (x2 + size * math.cos(a2), y2 + size * math.sin(a2))
    pts = f"{x2:.2f},{y2:.2f} {p1[0]:.2f},{p1[1]:.2f} {p2[0]:.2f},{p2[1]:.2f}"
    return (
        f'<polygon points="{pts}" fill="{color}" stroke="{color}" '
        f'stroke-width="1" stroke-linejoin="round" />'
    )


def _polyline_points(el: dict) -> list[tuple[float, float]]:
    x, y = el.get("x", 0), el.get("y", 0)
    pts = el.get("points") or [[0, 0], [el.get("width", 0), el.get("height", 0)]]
    return [(x + px, y + py) for px, py in pts]


def render_line(el: dict, is_arrow: bool = False) -> str:
    pts = _polyline_points(el)
    if len(pts) < 2:
        return ""
    # polylines should not fill
    el_no_fill = dict(el)
    el_no_fill["backgroundColor"] = "transparent"
    attrs = _stroke_attrs(el_no_fill)
    path_pts = " ".join(f"{px:.2f},{py:.2f}" for px, py in pts)
    out = f'<polyline points="{path_pts}"{attrs}{_transform(el)} />'
    if is_arrow:
        end_ah = el.get("endArrowhead", "arrow")
        start_ah = el.get("startArrowhead")
        sw = el.get("strokeWidth", 1)
        color = el.get("strokeColor") or "#000000"
        if end_ah:
            out += _arrowhead(pts[-2][0], pts[-2][1], pts[-1][0], pts[-1][1], color, sw)
        if start_ah:
            out += _arrowhead(pts[1][0], pts[1][1], pts[0][0], pts[0][1], color, sw)
    return out


def render_text(el: dict) -> str:
    x = el.get("x", 0)
    y = el.get("y", 0)
    w = el.get("width", 0)
    h = el.get("height", 0)
    text = el.get("text", "") or ""
    font_size = el.get("fontSize", 16)
    line_height = el.get("lineHeight", 1.25)
    # Excalidraw's own default fontFamily is 1 (Virgil, hand-drawn); use it for
    # both missing and unrecognized values so text without an explicit family
    # renders in the expected font rather than monospace.
    family = FONT_FAMILY_MAP.get(el.get("fontFamily", 1), FONT_FAMILY_MAP[1])
    color = el.get("strokeColor") or "#000000"
    align = el.get("textAlign", "left")
    valign = el.get("verticalAlign", "top")
    opacity = float(el.get("opacity", 100)) / 100.0

    anchor = {"left": "start", "center": "middle", "right": "end"}.get(align, "start")
    if anchor == "start":
        tx = x
    elif anchor == "middle":
        tx = x + w / 2
    else:
        tx = x + w

    lines = text.split("\n")
    line_h = font_size * line_height
    total_h = line_h * len(lines)
    if valign == "middle":
        first_baseline = y + (h - total_h) / 2 + font_size * 0.85
    elif valign == "bottom":
        first_baseline = y + h - total_h + font_size * 0.85
    else:
        first_baseline = y + font_size * 0.85

    tspans = []
    for i, ln in enumerate(lines):
        ty = first_baseline + i * line_h
        tspans.append(f'<tspan x="{tx:.2f}" y="{ty:.2f}">{sax.escape(ln)}</tspan>')
    return (
        f'<text font-family="{family}" font-size="{font_size}" '
        f'fill="{color}" opacity="{opacity}" text-anchor="{anchor}"'
        f"{_transform(el)}>{''.join(tspans)}</text>"
    )


def render_element(el: dict) -> str:
    t = el.get("type")
    if t == "rectangle":
        return render_rectangle(el)
    if t == "ellipse":
        return render_ellipse(el)
    if t == "diamond":
        return render_diamond(el)
    if t == "arrow":
        return render_line(el, is_arrow=True)
    if t == "line":
        return render_line(el, is_arrow=False)
    if t == "text":
        return render_text(el)
    return f"<!-- unsupported element type: {t} -->"


def build_svg(data: dict, padding: int = 80) -> tuple[str, int, int]:
    elements = [e for e in data.get("elements", []) if not e.get("isDeleted")]
    min_x, min_y, max_x, max_y = compute_bounding_box(elements)
    w = int(max_x - min_x + padding * 2)
    h = int(max_y - min_y + padding * 2)
    bg = (data.get("appState") or {}).get("viewBackgroundColor", "#ffffff")
    tx = -min_x + padding
    ty = -min_y + padding
    body = "\n".join(render_element(e) for e in elements)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}">'
        f'<rect width="100%" height="100%" fill="{bg}" />'
        f'<g transform="translate({tx:.2f}, {ty:.2f})">{body}</g>'
        f"</svg>"
    )
    return svg, w, h


# ---------- PNG scene embedding (format documented in SKILL.md) ----------


def embed_excalidraw_in_png(png_path: Path, scene_json: str) -> None:
    """Embed scene JSON as a tEXt chunk so excalidraw.com can re-open the PNG.

    See SKILL.md "Scene embedding in the PNG" for the format. Strips any
    pre-existing text chunks because Excalidraw's decoder reads only the
    first text chunk and fails if its keyword isn't ours.
    """
    png_data = png_path.read_bytes()
    if png_data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{png_path} is not a PNG")
    compressed = zlib.compress(scene_json.encode("utf-8"))
    bstring = compressed.decode("latin-1")
    envelope = json.dumps(
        {"version": "1", "encoding": "bstring", "compressed": True, "encoded": bstring}
    )
    keyword = b"application/vnd.excalidraw+json"
    text_data = keyword + b"\x00" + envelope.encode("latin-1")
    chunk_type = b"tEXt"
    chunk_crc = zlib.crc32(chunk_type + text_data) & 0xFFFFFFFF
    scene_chunk = (
        struct.pack(">I", len(text_data)) + chunk_type + text_data + struct.pack(">I", chunk_crc)
    )
    out = bytearray(png_data[:8])
    pos = 8
    while pos < len(png_data):
        length = struct.unpack(">I", png_data[pos : pos + 4])[0]
        ctype = png_data[pos + 4 : pos + 8]
        end = pos + 8 + length + 4
        chunk_bytes = png_data[pos:end]
        if ctype in (b"tEXt", b"iTXt", b"zTXt"):
            pos = end
            continue
        if ctype == b"IEND":
            out += scene_chunk
        out += chunk_bytes
        pos = end
    png_path.write_bytes(bytes(out))


# ---------- Driver ----------


def validate(data: dict) -> list[str]:
    errs: list[str] = []
    if data.get("type") != "excalidraw":
        errs.append(f"Expected type 'excalidraw', got {data.get('type')!r}")
    if "elements" not in data:
        errs.append("Missing 'elements' array")
    elif not isinstance(data["elements"], list):
        errs.append("'elements' must be an array")
    elif not data["elements"]:
        errs.append("'elements' is empty")
    return errs


def render(input_path: Path, output_path: Path | None, scale: int) -> Path:
    try:
        import cairosvg
    except ImportError:
        print(
            "ERROR: cairosvg is not available. Run this script via `uv run` so the\n"
            "       PEP 723 dependencies resolve, e.g.\n"
            "           uv run references/render_offline.py <file.excalidraw>\n"
            "       (or make it executable and run ./render_offline.py). Install uv\n"
            "       from https://docs.astral.sh/uv/ if it isn't on your PATH.",
            file=sys.stderr,
        )
        sys.exit(1)

    raw = input_path.read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"ERROR: Invalid JSON in {input_path}: {exc}", file=sys.stderr)
        sys.exit(1)
    errs = validate(data)
    if errs:
        for e in errs:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    svg, w, h = build_svg(data)

    if output_path is None:
        if input_path.suffix == ".excalidraw":
            output_path = Path(str(input_path) + ".png")
        else:
            output_path = input_path.with_suffix(".excalidraw.png")

    cairosvg.svg2png(
        bytestring=svg.encode("utf-8"),
        write_to=str(output_path),
        output_width=w * scale,
        output_height=h * scale,
    )
    embed_excalidraw_in_png(output_path, raw)
    return output_path


def main() -> None:
    p = argparse.ArgumentParser(description="Offline Excalidraw -> PNG renderer with scene embed")
    p.add_argument("input", type=Path)
    p.add_argument("--output", "-o", type=Path, default=None)
    p.add_argument("--scale", "-s", type=int, default=2)
    args = p.parse_args()
    if not args.input.exists():
        print(f"ERROR: file not found: {args.input}", file=sys.stderr)
        sys.exit(1)
    out = render(args.input, args.output, args.scale)
    print(str(out))


if __name__ == "__main__":
    main()
