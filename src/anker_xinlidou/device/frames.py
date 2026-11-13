"""安克录音豆（soundcore Work / D3200）的蓝牙帧格式与命令编码。

协议来自公开的逆向整理（tacshi/Soundcore 的 PROTOCOL.md）以及 MIT 许可的
soundcore-pull、recording-bean-web，用 Python 重新实现。不含任何固件或私钥。

TX（手机 → 设备）：08 EE 00 00 00 | type | id | 总长 u16 LE | payload | 校验和
RX（设备 → 手机）：09 FF 00 00 | status | type | id | 总长 u16 LE | payload | 校验和
"""

from __future__ import annotations

from dataclasses import dataclass, field


def checksum(data: bytes) -> int:
    return sum(data) & 0xFF


def encode(cmd_type: int, cmd_id: int, payload: bytes = b"") -> bytes:
    frame = bytearray([0x08, 0xEE, 0x00, 0x00, 0x00, cmd_type, cmd_id])
    total = 10 + len(payload)
    frame.append(total & 0xFF)
    frame.append((total >> 8) & 0xFF)
    frame.extend(payload)
    frame.append(checksum(frame))
    return bytes(frame)


def u16le(value: int) -> bytes:
    return bytes([value & 0xFF, (value >> 8) & 0xFF])


def u32le(value: int) -> bytes:
    return bytes([value & 0xFF, (value >> 8) & 0xFF, (value >> 16) & 0xFF, (value >> 24) & 0xFF])


# --- 命令 ---

def get_device_info() -> bytes:
    return encode(0x01, 0x01)


def sync_time(unix_seconds: int, tz_offset_hours: int) -> bytes:
    tz = tz_offset_hours & 0xFF
    return encode(0x01, 0xA6, u32le(unix_seconds) + bytes([tz]))


def list_files(page: int) -> bytes:
    return encode(0x1A, 0x0E, u16le(page))


def handshake(public_key: bytes) -> bytes:
    return encode(0x2E, 0x01, public_key)


def start_export(file_id: int, realtime: bool = False) -> bytes:
    """离线取整段录音用 realtime=False（偏移 0 + 实时标志 0）。"""
    return encode(0x1A, 0x07, u32le(0) + u32le(file_id) + bytes([1 if realtime else 0]))


def delete_file(file_id: int) -> bytes:
    return encode(0x1A, 0x10, u32le(file_id))


# --- 回包 ---

@dataclass
class Frame:
    raw: bytes
    status: int
    type: int
    id: int
    payload: bytes

    @property
    def hex(self) -> str:
        return " ".join(f"{b:02x}" for b in self.raw)


class PacketBuffer:
    """把蓝牙通知碎片拼回完整回包帧。"""

    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, fragment: bytes) -> list[Frame]:
        self._buffer.extend(fragment)
        frames: list[Frame] = []
        while len(self._buffer) >= 10:
            start = self._find_header()
            if start is None:
                self._buffer.clear()
                break
            if start > 0:
                del self._buffer[:start]
            if len(self._buffer) < 10:
                break
            total = self._buffer[7] | (self._buffer[8] << 8)
            if total < 10:
                del self._buffer[:1]
                continue
            if len(self._buffer) < total:
                break
            raw = bytes(self._buffer[:total])
            del self._buffer[:total]
            if checksum(raw[:-1]) != raw[-1]:
                continue
            frames.append(Frame(raw=raw, status=raw[4], type=raw[5], id=raw[6], payload=raw[9:-1]))
        return frames

    def _find_header(self) -> int | None:
        b = self._buffer
        if len(b) < 4:
            return None
        for i in range(len(b) - 3):
            if b[i] == 0x09 and b[i + 1] == 0xFF and b[i + 2] == 0x00 and b[i + 3] == 0x00:
                return i
        return None


def _u32(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset:offset + 4], "little")


def _u16(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset:offset + 2], "little")


def _ascii(data: bytes, start: int, length: int) -> str:
    chunk = data[start:start + length]
    chunk = chunk.split(b"\x00", 1)[0]
    return chunk.decode("utf-8", "ignore").strip()


@dataclass
class DeviceInfo:
    battery_percent: int | None = None
    charging: bool = False
    firmware: str = ""
    serial: str = ""
    recording: bool = False

    @staticmethod
    def battery_from_byte(raw: int) -> int:
        value = raw & 0x7F
        return (value + 1) * 10 if value <= 9 else min(value, 100)

    @classmethod
    def parse(cls, p: bytes) -> "DeviceInfo":
        info = cls()
        if len(p) < 3:
            return info
        info.battery_percent = cls.battery_from_byte(p[1])
        info.charging = p[2] == 1
        offset = 3
        if len(p) >= offset + 5:
            info.firmware = _ascii(p, offset, 5)
            offset += 5
        if len(p) >= offset + 16:
            info.serial = _ascii(p, offset, 16).lower()
            offset += 16
        if len(p) >= offset + 8:
            offset += 8  # 总容量、剩余容量，不保存
        recording_offset = offset + 1 + 5 + 1 + 6 + 5
        if len(p) > recording_offset:
            info.recording = p[recording_offset] == 1
        return info


@dataclass
class RecordingEntry:
    file_id: int          # 录音开始时间的 Unix 时间戳（秒）
    duration_ms: int

    @classmethod
    def parse_list(cls, p: bytes) -> list["RecordingEntry"]:
        if len(p) < 2:
            return []
        count = _u16(p, 0)
        entries: list[RecordingEntry] = []
        offset = 2
        for _ in range(count):
            if offset + 8 > len(p):
                break
            entry = cls(file_id=_u32(p, offset), duration_ms=_u32(p, offset + 4))
            offset += 8
            if entry.duration_ms > 0:
                entries.append(entry)
        return entries


def active_file_id(p: bytes, entry_width: int = 8) -> int | None:
    """文件列表末尾「正在录的文件 id」，没有在录时为 0。"""
    if len(p) < 2:
        return None
    count = _u16(p, 0)
    trailer = 2 + count * entry_width
    if count > 1000 or len(p) < trailer + 4:
        return None
    value = _u32(p, trailer)
    return None if value == 0 else value


SLICE_BYTES = 166
AUDIO_BYTES = 160


def parse_slices(payload: bytes) -> list[tuple[int, bytes]]:
    """一条音频通知里的若干切片：序号 u32 LE、标志 1 字节、加密音频 160 字节、尾字节。"""
    result: list[tuple[int, bytes]] = []
    offset = 0
    while len(payload) - offset >= 165:
        seq = _u32(payload, offset)
        start = offset + 5
        result.append((seq, payload[start:start + AUDIO_BYTES]))
        offset += SLICE_BYTES
    return result
