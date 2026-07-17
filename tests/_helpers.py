"""Byte-level helpers for building PNGs and Excalidraw scene envelopes.

Kept separate from ``conftest.py`` so tests can import the builders directly.
The PNGs produced here are structurally valid (correct magic, chunk lengths
and CRCs) but are *not* real images — ``extract_scene`` only walks chunks and
never decodes the pixel data, so a dummy ``IDAT`` is enough to exercise it
without pulling in a rasterizer.
"""

from __future__ import annotations

import base64
import json
import struct
import zlib

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
EXCALIDRAW_KEYWORD = b"application/vnd.excalidraw+json"


def png_chunk(ctype: bytes, data: bytes) -> bytes:
    """Serialize one PNG chunk: length + type + data + CRC32(type+data)."""
    crc = zlib.crc32(ctype + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + ctype + data + struct.pack(">I", crc)


def build_png(text_chunks: tuple[bytes, ...] = ()) -> bytes:
    """Assemble a minimal, chunk-valid PNG with optional text chunks.

    ``text_chunks`` are raw chunk *bodies* (keyword + NUL + value); each is
    written as a ``tEXt`` chunk between IHDR and IDAT.
    """
    out = bytearray(PNG_MAGIC)
    out += png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    for body in text_chunks:
        out += png_chunk(b"tEXt", body)
    out += png_chunk(b"IDAT", b"\x00")
    out += png_chunk(b"IEND", b"")
    return bytes(out)


def make_envelope(
    scene: dict,
    *,
    encoding: str = "bstring",
    compressed: bool = True,
    wbits: int = zlib.MAX_WBITS,
) -> str:
    """Build the ``{version,encoding,compressed,encoded}`` envelope string."""
    raw = json.dumps(scene).encode("utf-8")
    if compressed:
        compressor = zlib.compressobj(wbits=wbits)
        raw = compressor.compress(raw) + compressor.flush()
    if encoding == "bstring":
        encoded = raw.decode("latin-1")
    elif encoding == "base64":
        encoded = base64.b64encode(raw).decode("ascii")
    else:
        raise ValueError(f"unknown encoding {encoding!r}")
    return json.dumps(
        {"version": "1", "encoding": encoding, "compressed": compressed, "encoded": encoded}
    )


def scene_text_body(scene: dict, **kwargs) -> bytes:
    """A tEXt chunk body carrying the Excalidraw scene envelope."""
    envelope = make_envelope(scene, **kwargs)
    return EXCALIDRAW_KEYWORD + b"\x00" + envelope.encode("latin-1")


def scene_png(scene: dict, **kwargs) -> bytes:
    """A chunk-valid PNG carrying ``scene`` in a tEXt chunk."""
    return build_png((scene_text_body(scene, **kwargs),))
