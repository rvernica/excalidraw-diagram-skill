#!/usr/bin/env python3
"""Extract the embedded Excalidraw scene JSON from a `.excalidraw.png`.

The inverse of `embed_excalidraw_in_png` in render_offline.py. An
`.excalidraw.png` is a normal PNG that *also* carries the editable scene
in a `tEXt` chunk (keyword `application/vnd.excalidraw+json`). Reading the
PNG as an image only gives you pixels; this script recovers the canonical
scene JSON — exact text, coordinates, bindings — so you can edit and
re-render without eyeballing the picture.

Pure stdlib: no browser, no network, no third-party deps, no setup.

Usage:
    ./extract_scene.py <file.excalidraw.png>              # scene JSON -> stdout
    ./extract_scene.py <file.excalidraw.png> -o out.excalidraw
    ./extract_scene.py <file.excalidraw.png> --output auto # -> sibling .excalidraw
    ./extract_scene.py <file.excalidraw.png> --pretty      # 2-space indented
    ./extract_scene.py <file.excalidraw.png> --info        # chunk + element summary

Envelope format (what render_offline.py and excalidraw.com write):
    {"version":"1","encoding":"bstring","compressed":true,"encoded":"<...>"}
The `encoded` field is the (zlib-)compressed scene JSON as a Latin-1
string. Older / alternate exporters may use base64 or leave it raw; this
script tries each in turn so it round-trips scenes from any source.
"""

from __future__ import annotations

import argparse
import base64
import json
import struct
import sys
import zlib
from pathlib import Path

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
EXCALIDRAW_KEYWORD = b"application/vnd.excalidraw+json"


class SceneError(Exception):
    """No usable Excalidraw scene could be recovered from the PNG."""


def iter_chunks(png: bytes):
    """Yield (ctype: bytes, data: bytes) for each PNG chunk, bounds-checked."""
    if png[:8] != PNG_MAGIC:
        raise SceneError("not a PNG (bad magic bytes)")
    pos = 8
    n = len(png)
    while pos + 8 <= n:
        (length,) = struct.unpack(">I", png[pos:pos + 4])
        ctype = png[pos + 4:pos + 8]
        data_start = pos + 8
        data_end = data_start + length
        if data_end + 4 > n:
            raise SceneError(f"truncated PNG: chunk {ctype!r} runs past EOF")
        yield ctype, png[data_start:data_end]
        pos = data_end + 4  # skip the 4-byte CRC


def find_scene_text(png: bytes) -> str:
    """Return the raw envelope string from the excalidraw text chunk.

    Handles tEXt and iTXt (both store the keyword before a NUL). zTXt is
    not emitted by Excalidraw and is skipped.
    """
    for ctype, data in iter_chunks(png):
        if ctype not in (b"tEXt", b"iTXt"):
            continue
        keyword, _, rest = data.partition(b"\x00")
        if keyword != EXCALIDRAW_KEYWORD:
            continue
        if ctype == b"iTXt":
            # iTXt: keyword\0 compression_flag(1) compression_method(1)
            #       language\0 translated_keyword\0 text
            rest = rest[2:]  # drop compression flag + method bytes
            _, _, rest = rest.partition(b"\x00")  # language tag
            _, _, rest = rest.partition(b"\x00")  # translated keyword
        return rest.decode("latin-1")
    raise SceneError(
        "no Excalidraw scene found: PNG has no tEXt/iTXt chunk with keyword "
        f"{EXCALIDRAW_KEYWORD.decode()!r} "
        "(this is the 'Image doesn't contain scene' case)"
    )


def _decompress(raw: bytes) -> bytes:
    """Try the compression formats exporters use, most common first."""
    for wbits in (zlib.MAX_WBITS, -zlib.MAX_WBITS, zlib.MAX_WBITS | 16):
        try:
            return zlib.decompress(raw, wbits)
        except zlib.error:
            continue
    raise SceneError("scene payload is marked compressed but could not be inflated")


def decode_envelope(envelope_str: str) -> str:
    """Turn the text-chunk value into scene JSON text.

    Excalidraw wraps the scene in {version, encoding, compressed, encoded}.
    We also accept a bare scene object (no envelope) for robustness.
    """
    try:
        env = json.loads(envelope_str)
    except json.JSONDecodeError as exc:
        raise SceneError(f"text chunk is not valid JSON: {exc}") from exc

    # Already a scene, not an envelope (e.g. some hand-made PNGs).
    if isinstance(env, dict) and env.get("type") == "excalidraw":
        return envelope_str
    if not isinstance(env, dict) or "encoded" not in env:
        raise SceneError("text chunk JSON is neither an envelope nor a scene")

    encoded = env["encoded"]
    if env.get("encoding") == "bstring":
        raw = encoded.encode("latin-1")
    else:  # historical exports use base64
        try:
            raw = base64.b64decode(encoded)
        except (ValueError, TypeError):
            raw = encoded.encode("latin-1")

    if env.get("compressed"):
        raw = _decompress(raw)

    return raw.decode("utf-8")


def recover_scene(png: bytes) -> tuple[str, dict]:
    """Return (raw scene JSON text, parsed scene dict) from PNG bytes.

    Single decode pass: callers that want the exact round-trip bytes and the
    parsed object both read from one recovery instead of re-decoding.
    """
    scene_json = decode_envelope(find_scene_text(png))
    try:
        scene = json.loads(scene_json)
    except json.JSONDecodeError as exc:
        raise SceneError(f"recovered scene is not valid JSON: {exc}") from exc
    if scene.get("type") != "excalidraw":
        raise SceneError(
            f"recovered JSON is not an Excalidraw scene (type={scene.get('type')!r})"
        )
    return scene_json, scene


def extract_scene(png_path: Path) -> dict:
    """Read a PNG and return the parsed Excalidraw scene dict."""
    return recover_scene(png_path.read_bytes())[1]


def print_info(png_path: Path) -> None:
    """Print a chunk layout + scene summary to stderr (diagnosis mode)."""
    png = png_path.read_bytes()
    print(f"{png_path}", file=sys.stderr)
    has_scene_chunk = False
    for ctype, data in iter_chunks(png):
        label = ctype.decode("latin-1", "replace")
        extra = ""
        if ctype in (b"tEXt", b"iTXt", b"zTXt"):
            keyword = data.partition(b"\x00")[0].decode("latin-1", "replace")
            extra = f"  keyword={keyword!r}"
            if data.partition(b"\x00")[0] == EXCALIDRAW_KEYWORD:
                has_scene_chunk = True
        print(f"  {label:5s}  len={len(data)}{extra}", file=sys.stderr)
    if not has_scene_chunk:
        print("  -> no embedded Excalidraw scene", file=sys.stderr)
        return
    scene = extract_scene(png_path)
    elements = scene.get("elements", [])
    by_type: dict[str, int] = {}
    for el in elements:
        by_type[el.get("type", "?")] = by_type.get(el.get("type", "?"), 0) + 1
    print(f"  -> scene version {scene.get('version')}, "
          f"{len(elements)} elements: {by_type}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract embedded Excalidraw scene JSON from a .excalidraw.png",
    )
    parser.add_argument("png", type=Path, help="path to a .excalidraw.png file")
    parser.add_argument(
        "-o", "--output",
        help="write scene JSON here; '-' for stdout (default), "
             "'auto' for a sibling .excalidraw file",
    )
    parser.add_argument(
        "--pretty", action="store_true",
        help="re-serialize with 2-space indentation (default: exact bytes)",
    )
    parser.add_argument(
        "--info", action="store_true",
        help="print PNG chunk layout + scene summary to stderr and exit",
    )
    args = parser.parse_args()

    if not args.png.is_file():
        print(f"ERROR: no such file: {args.png}", file=sys.stderr)
        sys.exit(1)

    try:
        if args.info:
            print_info(args.png)
            return

        scene_json, scene = recover_scene(args.png.read_bytes())
        if args.pretty:
            text = json.dumps(scene, indent=2, ensure_ascii=False)
        else:
            # exact round-trip: re-emit the recovered JSON untouched
            text = scene_json
    except SceneError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(2)

    if args.output in (None, "-"):
        sys.stdout.write(text)
        if not text.endswith("\n"):
            sys.stdout.write("\n")
        return

    if args.output == "auto":
        name = args.png.name
        stem = name[:-len(".excalidraw.png")] if name.endswith(".excalidraw.png") \
            else args.png.stem
        out_path = args.png.with_name(stem + ".excalidraw")
    else:
        out_path = Path(args.output)
    out_path.write_text(text, encoding="utf-8")
    print(f"Wrote {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
