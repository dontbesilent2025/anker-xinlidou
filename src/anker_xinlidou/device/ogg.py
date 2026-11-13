"""把录音豆的 160 字节 Opus 帧（48 kHz 单声道、20 ms）封装成标准 Ogg/Opus。

任何解码器（ffmpeg、libopus、whisper）都能读这种文件。
逻辑移植自 MIT 许可的 soundcore-pull。
"""

from __future__ import annotations

FRAME_SIZE = 160
SAMPLES_PER_FRAME = 960
SAMPLE_RATE = 48000
_SERIAL = 0x4152_4B52


def _u32(value: int) -> bytes:
    return (value & 0xFFFFFFFF).to_bytes(4, "little")


def _crc32(data: bytes) -> int:
    """Ogg CRC：多项式 0x04C11DB7，不反转，初值 0，不异或输出。"""
    crc = 0
    for byte in data:
        crc ^= byte << 24
        for _ in range(8):
            crc = ((crc << 1) ^ 0x04C1_1DB7) & 0xFFFFFFFF if crc & 0x8000_0000 else (crc << 1) & 0xFFFFFFFF
    return crc


def _page(packets: list[bytes], sequence: int, granule: int, flags: int) -> bytes:
    segments = bytearray()
    for packet in packets:
        remaining = len(packet)
        while remaining >= 255:
            segments.append(255)
            remaining -= 255
        segments.append(remaining)
    header = bytearray(b"OggS")
    header.append(0)
    header.append(flags)
    header.extend((granule & 0xFFFFFFFFFFFFFFFF).to_bytes(8, "little"))
    header.extend(_u32(_SERIAL))
    header.extend(_u32(sequence))
    header.extend(_u32(0))  # CRC 占位
    header.append(len(segments))
    header.extend(segments)
    page = bytearray(header)
    for packet in packets:
        page.extend(packet)
    crc = _crc32(bytes(page))
    page[22:26] = _u32(crc)
    return bytes(page)


def mux(raw: bytes) -> bytes:
    """把连续的 160 字节 Opus 帧封装成 Ogg 字节流。"""
    frames: list[bytes] = []
    for offset in range(0, len(raw), FRAME_SIZE):
        frame = bytearray(raw[offset:offset + FRAME_SIZE])
        while frame and frame[-1] == 0:
            frame.pop()
        frames.append(bytes(frame) if frame else b"\x00")

    head = bytearray(b"OpusHead")
    head.extend([1, 1])            # 版本、声道数
    head.extend([0x00, 0x0F])      # pre-skip 3840 LE
    head.extend(_u32(SAMPLE_RATE))
    head.extend([0, 0])            # output gain
    head.append(0)                 # channel mapping family

    vendor = b"anker-xinlidou"
    tags = bytearray(b"OpusTags")
    tags.extend(_u32(len(vendor)))
    tags.extend(vendor)
    tags.extend(_u32(0))

    out = bytearray()
    out.extend(_page([bytes(head)], sequence=0, granule=0, flags=0x02))
    out.extend(_page([bytes(tags)], sequence=1, granule=0, flags=0))
    granule = 0
    sequence = 2
    start = 0
    while start < len(frames):
        batch = frames[start:start + 50]
        granule += len(batch) * SAMPLES_PER_FRAME
        is_last = start + 50 >= len(frames)
        out.extend(_page(batch, sequence=sequence, granule=granule, flags=0x04 if is_last else 0))
        sequence += 1
        start += 50
    return bytes(out)
