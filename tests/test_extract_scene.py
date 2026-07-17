"""Tests for references/extract_scene.py."""

from __future__ import annotations

import json
import struct
import zlib

import pytest

import extract_scene as es
from _helpers import (
    EXCALIDRAW_KEYWORD,
    PNG_MAGIC,
    build_png,
    make_envelope,
    png_chunk,
    scene_png,
)


def _png_with_chunk(ctype: bytes, body: bytes) -> bytes:
    """A chunk-valid PNG carrying one extra chunk of ``ctype`` before IDAT."""
    out = bytearray(PNG_MAGIC)
    out += png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    out += png_chunk(ctype, body)
    out += png_chunk(b"IDAT", b"\x00")
    out += png_chunk(b"IEND", b"")
    return bytes(out)


# ---------- iter_chunks ----------


def test_iter_chunks_yields_types_in_order():
    png = build_png()
    types = [ctype for ctype, _ in es.iter_chunks(png)]
    assert types == [b"IHDR", b"IDAT", b"IEND"]


def test_iter_chunks_rejects_bad_magic():
    with pytest.raises(es.SceneError, match="not a PNG"):
        list(es.iter_chunks(b"not a png at all"))


def test_iter_chunks_rejects_truncated_chunk():
    png = build_png()[:-3]  # chop into the final CRC
    with pytest.raises(es.SceneError, match="truncated"):
        list(es.iter_chunks(png))


# ---------- find_scene_text ----------


def test_find_scene_text_reads_text_chunk(sample_scene):
    envelope = make_envelope(sample_scene)
    png = scene_png(sample_scene)
    assert es.find_scene_text(png) == envelope


def test_find_scene_text_reads_itxt_chunk(sample_scene):
    envelope = make_envelope(sample_scene)
    # iTXt body: keyword\0 comp_flag(1) comp_method(1) lang\0 translated\0 text
    body = (
        EXCALIDRAW_KEYWORD
        + b"\x00"
        + b"\x00"
        + b"\x00"  # not compressed
        + b"\x00"  # empty language tag
        + b"\x00"  # empty translated keyword
        + envelope.encode("latin-1")
    )
    png = _png_with_chunk(b"iTXt", body)
    assert es.find_scene_text(png) == envelope


def test_find_scene_text_missing_raises():
    with pytest.raises(es.SceneError, match="no Excalidraw scene"):
        es.find_scene_text(build_png())


def test_find_scene_text_ignores_other_keyword():
    body = b"Software\x00excalidraw.com"
    png = _png_with_chunk(b"tEXt", body)
    with pytest.raises(es.SceneError, match="no Excalidraw scene"):
        es.find_scene_text(png)


# ---------- _decompress ----------


@pytest.mark.parametrize("wbits", [zlib.MAX_WBITS, -zlib.MAX_WBITS, zlib.MAX_WBITS | 16])
def test_decompress_handles_each_format(wbits):
    payload = b"hello scene payload"
    comp = zlib.compressobj(wbits=wbits)
    raw = comp.compress(payload) + comp.flush()
    assert es._decompress(raw) == payload


def test_decompress_rejects_garbage():
    with pytest.raises(es.SceneError, match="could not be inflated"):
        es._decompress(b"\x00\x01\x02 not compressed")


# ---------- decode_envelope ----------


def test_decode_envelope_bstring_compressed(sample_scene):
    envelope = make_envelope(sample_scene, encoding="bstring", compressed=True)
    assert json.loads(es.decode_envelope(envelope)) == sample_scene


def test_decode_envelope_base64_compressed(sample_scene):
    envelope = make_envelope(sample_scene, encoding="base64", compressed=True)
    assert json.loads(es.decode_envelope(envelope)) == sample_scene


def test_decode_envelope_base64_uncompressed(sample_scene):
    envelope = make_envelope(sample_scene, encoding="base64", compressed=False)
    assert json.loads(es.decode_envelope(envelope)) == sample_scene


def test_decode_envelope_accepts_bare_scene(sample_scene):
    bare = json.dumps(sample_scene)
    assert es.decode_envelope(bare) == bare


def test_decode_envelope_rejects_non_json():
    with pytest.raises(es.SceneError, match="not valid JSON"):
        es.decode_envelope("<<< not json >>>")


def test_decode_envelope_rejects_missing_encoded():
    with pytest.raises(es.SceneError, match="neither an envelope nor a scene"):
        es.decode_envelope(json.dumps({"version": "1"}))


# ---------- recover_scene / extract_scene ----------


def test_recover_scene_round_trips(sample_scene):
    scene_json, scene = es.recover_scene(scene_png(sample_scene))
    assert scene == sample_scene
    assert json.loads(scene_json) == sample_scene


def test_recover_scene_rejects_wrong_type():
    png = scene_png({"type": "notexcalidraw", "elements": []})
    with pytest.raises(es.SceneError, match="not an Excalidraw scene"):
        es.recover_scene(png)


def test_extract_scene_reads_file(tmp_path, sample_scene):
    path = tmp_path / "d.excalidraw.png"
    path.write_bytes(scene_png(sample_scene))
    assert es.extract_scene(path) == sample_scene


# ---------- CLI (main) ----------


def _write_png(tmp_path, sample_scene, name="d.excalidraw.png"):
    path = tmp_path / name
    path.write_bytes(scene_png(sample_scene))
    return path


def test_cli_writes_scene_to_stdout(tmp_path, sample_scene, monkeypatch, capsys):
    path = _write_png(tmp_path, sample_scene)
    monkeypatch.setattr("sys.argv", ["extract_scene.py", str(path)])
    es.main()
    out = capsys.readouterr().out
    assert json.loads(out) == sample_scene


def test_cli_output_file(tmp_path, sample_scene, monkeypatch):
    path = _write_png(tmp_path, sample_scene)
    dest = tmp_path / "out.excalidraw"
    monkeypatch.setattr("sys.argv", ["extract_scene.py", str(path), "-o", str(dest)])
    es.main()
    assert json.loads(dest.read_text()) == sample_scene


def test_cli_output_auto_sibling(tmp_path, sample_scene, monkeypatch):
    path = _write_png(tmp_path, sample_scene, name="diagram.excalidraw.png")
    monkeypatch.setattr("sys.argv", ["extract_scene.py", str(path), "--output", "auto"])
    es.main()
    sibling = tmp_path / "diagram.excalidraw"
    assert sibling.is_file()
    assert json.loads(sibling.read_text()) == sample_scene


def test_cli_pretty_is_indented(tmp_path, sample_scene, monkeypatch, capsys):
    path = _write_png(tmp_path, sample_scene)
    monkeypatch.setattr("sys.argv", ["extract_scene.py", str(path), "--pretty"])
    es.main()
    out = capsys.readouterr().out
    assert "\n  " in out  # 2-space indentation
    assert json.loads(out) == sample_scene


def test_cli_info_summary(tmp_path, sample_scene, monkeypatch, capsys):
    path = _write_png(tmp_path, sample_scene)
    monkeypatch.setattr("sys.argv", ["extract_scene.py", str(path), "--info"])
    es.main()
    err = capsys.readouterr().err
    assert "scene version" in err
    assert "'application/vnd.excalidraw+json'" in err


def test_cli_missing_file_exits_1(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["extract_scene.py", str(tmp_path / "nope.png")])
    with pytest.raises(SystemExit) as exc:
        es.main()
    assert exc.value.code == 1
    assert "no such file" in capsys.readouterr().err


def test_cli_no_scene_exits_2(tmp_path, monkeypatch, capsys):
    path = tmp_path / "plain.png"
    path.write_bytes(build_png())  # valid PNG, no scene chunk
    monkeypatch.setattr("sys.argv", ["extract_scene.py", str(path)])
    with pytest.raises(SystemExit) as exc:
        es.main()
    assert exc.value.code == 2
    assert "no Excalidraw scene" in capsys.readouterr().err


def test_cli_info_no_scene_does_not_exit(tmp_path, monkeypatch, capsys):
    path = tmp_path / "plain.png"
    path.write_bytes(build_png())
    monkeypatch.setattr("sys.argv", ["extract_scene.py", str(path), "--info"])
    es.main()  # must return normally
    assert "no embedded Excalidraw scene" in capsys.readouterr().err
