"""离线自测：不连设备、不需要真实录音。协议、存储、MCP 工具形状都在这里验证。

真机同步(蓝牙)和 whisper 转写需要设备和模型,单独手动验收,不在这里。
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from anker_xinlidou.device import crypto, frames, ogg

FIXTURE = Path(__file__).parent / "sine440.opusraw"


# --- 协议 ---

def test_aes_ctr_nist_vector():
    key = bytes.fromhex("603deb1015ca71be2b73aef0857d77811f352c073b6108d72d9810a30914dff4")
    iv = bytes.fromhex("f0f1f2f3f4f5f6f7f8f9fafbfcfdfeff")
    ct = bytes.fromhex("601ec313775789a5b7a7f504bbf3d228")
    assert crypto.aes_ctr(ct, key, iv) == bytes.fromhex("6bc1bee22e409f96e93d7e117393172a")


def test_public_key_is_uncompressed_p256():
    pk = crypto.DeviceCrypto().public_key
    assert len(pk) == 65 and pk[0] == 0x04


def test_frame_encoding():
    assert list(frames.get_device_info()) == [0x08, 0xEE, 0, 0, 0, 0x01, 0x01, 0x0A, 0x00, 0x02]
    assert list(frames.list_files(1)) == [0x08, 0xEE, 0, 0, 0, 0x1A, 0x0E, 0x0C, 0x00, 0x01, 0x00, 0x2B]
    sr = frames.start_export(0x01020304, realtime=False)
    assert list(sr[9:18]) == [0, 0, 0, 0, 0x04, 0x03, 0x02, 0x01, 0]


def test_packet_buffer_reassembles():
    payload = bytes([0x02, 0x00]) + frames.u32le(0) + frames.u32le(0)
    body = bytes([0x09, 0xFF, 0x00, 0x00, 0x01, 0x1A, 0x0E])
    total = 10 + len(payload)
    body += bytes([total & 0xFF, total >> 8]) + payload
    body += bytes([frames.checksum(body)])
    buf = frames.PacketBuffer()
    assert buf.feed(bytes([0xAA]) + body[:6]) == []
    got = buf.feed(body[6:])
    assert len(got) == 1 and got[0].type == 0x1A and got[0].id == 0x0E


def test_file_list_and_active():
    p = bytes([0x01, 0x00]) + frames.u32le(1700000000) + frames.u32le(30000)
    p += frames.u32le(1700000500) + frames.u32le(1200)
    entries = frames.RecordingEntry.parse_list(p)
    assert len(entries) == 1 and entries[0].file_id == 1700000000
    assert frames.active_file_id(p) == 1700000500


def test_slice_parsing():
    payload = b""
    for seq in (7, 8):
        payload += frames.u32le(seq) + bytes([0]) + bytes([seq]) * 160 + bytes([0])
    slices = frames.parse_slices(payload)
    assert [s[0] for s in slices] == [7, 8]
    assert slices[1][1] == bytes([8]) * 160


@pytest.mark.skipif(not FIXTURE.exists(), reason="需要 sine440.opusraw")
def test_ogg_mux_decodes_to_440hz():
    import struct
    data = ogg.mux(FIXTURE.read_bytes())
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
        f.write(data)
        ogg_path = f.name
    pcm_path = ogg_path + ".pcm"
    try:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", ogg_path,
                        "-f", "s16le", "-ac", "1", "-ar", "16000", pcm_path], check=True)
        raw = Path(pcm_path).read_bytes()
        vals = struct.unpack(f"<{len(raw)//2}h", raw)
        tail = vals[3200:len(vals) - 320]
        crossings = sum(1 for i in range(1, len(tail)) if (tail[i-1] < 0) != (tail[i] < 0))
        freq = crossings / 2 / (len(tail) / 16000)
        assert abs(freq - 440) < 12, freq
    finally:
        for p in (ogg_path, pcm_path):
            try:
                os.unlink(p)
            except OSError:
                pass


# --- 存储 ---

def test_store_crud_and_search(tmp_path):
    from anker_xinlidou.store import Store
    store = Store(tmp_path)
    store.add_audio(1700000000, 30000, str(tmp_path / "a.ogg"))
    assert store.has(1700000000)
    assert store.pending_transcription()[0].file_id == 1700000000
    store.set_raw_text(1700000000, "今天开会讨论泛直")
    assert store.pending_correction()[0].raw_text == "今天开会讨论泛直"
    store.save_correction(1700000000, "今天开会讨论泛直。")
    seg = store.get(1700000000)
    assert seg.corrected and seg.text == "今天开会讨论泛直。"
    assert store.search("泛直")[0].file_id == 1700000000
    assert store.list_range(1600000000, 1800000000)
    store.close()


def test_glossary(tmp_path, monkeypatch):
    monkeypatch.setenv("ANKER_XINLIDOU_HOME", str(tmp_path))
    from anker_xinlidou import glossary
    assert "术语表" in glossary.read_glossary()
    glossary.write_glossary("泛直\n栋哥\n# 注释\n")
    assert glossary.glossary_terms() == ["泛直", "栋哥"]


# --- 装配 ---

def test_mcp_server_imports_and_registers_tools():
    from anker_xinlidou import mcp_server
    assert mcp_server.server is not None


def test_device_sync_imports():
    from anker_xinlidou.device import sync, recorder
    assert hasattr(sync, "sync") and hasattr(recorder, "scan")
