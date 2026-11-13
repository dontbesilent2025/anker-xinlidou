"""离线同步：把录音豆里还没拉过的录音整段取下来、解密、存成 Ogg。

不删除设备上的录音，不解绑飞书，不发送绑定/恢复出厂/升级命令。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from . import frames as F
from .crypto import DeviceCrypto
from .ogg import mux
from .recorder import Recorder, find_and_open

log = logging.getLogger("anker_xinlidou.sync")


class SerialMismatch(Exception):
    def __init__(self, got: str, want: str) -> None:
        super().__init__(f"连到的录音豆序列号 {got} 不是期望的 {want}")
        self.got = got
        self.want = want


@dataclass
class SyncResult:
    serial: str = ""
    firmware: str = ""
    battery: int | None = None
    new_segments: list[int] = field(default_factory=list)   # 这次新拉到的 file_id
    skipped: int = 0                                         # 已有、跳过的数量
    errors: list[str] = field(default_factory=list)


async def _device_info(recorder: Recorder) -> F.DeviceInfo:
    reply = await recorder.request(F.get_device_info(), 0x01, 0x01, timeout=8, what="设备信息")
    return F.DeviceInfo.parse(reply.payload)


async def _list_entries(recorder: Recorder) -> list[F.RecordingEntry]:
    seen: dict[int, F.RecordingEntry] = {}
    for page in range(50):
        reply = await recorder.request(F.list_files(page), 0x1A, 0x0E, timeout=6, what="文件列表")
        entries = F.RecordingEntry.parse_list(reply.payload)
        before = len(seen)
        for e in entries:
            seen[e.file_id] = e
        if len(seen) == before:
            break
    return sorted(seen.values(), key=lambda e: e.file_id)


async def _pull_one(recorder: Recorder, crypto: DeviceCrypto, entry: F.RecordingEntry) -> bytes:
    """取一整段录音，返回解密后的连续 Opus 字节。"""
    if not crypto.has_session:
        reply = await recorder.request(F.handshake(crypto.public_key), 0x2E, 0x01, timeout=12,
                                       what="交换密钥")
        crypto.complete_handshake(reply.payload)
    audio = bytearray()
    last_seq: int | None = None
    await recorder.send(F.start_export(entry.file_id, realtime=False))
    try:
        while True:
            frame = await recorder.next_frame(timeout=90)
            if frame.type not in (0x1A, 0x1B):
                continue
            if frame.id == 0x07:
                crypto.prepare_file(frame.payload)
            elif frame.id in (0x08, 0x12):
                for seq, data in F.parse_slices(frame.payload):
                    if last_seq is not None and seq <= last_seq:
                        continue
                    last_seq = seq
                    audio.extend(crypto.decrypt_chunk(entry.file_id, seq, data))
            elif frame.id == 0x0A:
                break
    finally:
        crypto.clear_file(entry.file_id)
    if not audio:
        raise RuntimeError("这段录音没有拿到音频")
    return bytes(audio)


async def sync(store, *, address: str | None = None, serial: str | None = None,
               scan_timeout: float = 8.0, progress=None) -> SyncResult:
    """把录音豆里 store 还没有的录音都拉下来。progress(done, total) 可选回调。"""
    result = SyncResult()
    async with find_and_open(address, serial, scan_timeout) as recorder:
        info = await _device_info(recorder)
        result.serial = info.serial
        result.firmware = info.firmware
        result.battery = info.battery_percent
        if serial and info.serial and info.serial != serial:
            raise SerialMismatch(info.serial, serial)

        # 同步时间，保持设备时钟和本机一致（file_id 用它打戳）
        offset_hours = -(time.timezone // 3600) if not time.daylight else -(time.altzone // 3600)
        await recorder.request(F.sync_time(int(time.time()), offset_hours), 0x01, 0xA6,
                               timeout=8, what="同步时间")

        entries = await _list_entries(recorder)
        todo = [e for e in entries if not store.has(e.file_id)]
        crypto = DeviceCrypto()
        for i, entry in enumerate(todo):
            try:
                opus = await _pull_one(recorder, crypto, entry)
                path = store.audio_dir / f"{entry.file_id}.ogg"
                path.write_bytes(mux(opus))
                store.add_audio(entry.file_id, entry.duration_ms, str(path))
                result.new_segments.append(entry.file_id)
                log.info("拉到录音 %s（%.1f 秒）", entry.file_id, entry.duration_ms / 1000)
            except Exception as exc:  # 单段失败不影响其余
                result.errors.append(f"{entry.file_id}: {exc}")
                log.warning("录音 %s 拉取失败：%s", entry.file_id, exc)
            if progress:
                progress(i + 1, len(todo))
        result.skipped = len(entries) - len(todo)
    return result
