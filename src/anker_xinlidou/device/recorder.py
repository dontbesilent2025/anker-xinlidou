"""与一颗录音豆之间的蓝牙连接（基于 bleak，跨平台）。

扫描时只找录音豆的服务号；附近可能有别人的录音豆，用序列号确认是不是自己的。
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from bleak import BleakClient, BleakScanner

from .frames import Frame, PacketBuffer

log = logging.getLogger("anker_xinlidou.ble")

SERVICE_UUID = "020cf5da-0000-1000-8000-00805f9b34fb"
WRITE_UUID = "00007777-0000-1000-8000-00805f9b34fb"
NOTIFY_UUID = "00008888-0000-1000-8000-00805f9b34fb"


class RecorderError(Exception):
    pass


class NotFound(RecorderError):
    pass


async def scan(timeout: float = 8.0) -> list[tuple[str, int]]:
    """返回附近的录音豆 [(address, rssi)]，信号强的在前。"""
    found: dict[str, int] = {}
    devices = await BleakScanner.discover(timeout=timeout, service_uuids=[SERVICE_UUID], return_adv=True)
    for address, (device, adv) in devices.items():
        if SERVICE_UUID.lower() in [u.lower() for u in (adv.service_uuids or [])]:
            found[address] = adv.rssi if adv.rssi is not None else -127
    return sorted(found.items(), key=lambda kv: kv[1], reverse=True)


class Recorder:
    """一次蓝牙会话。用 async with 打开。"""

    def __init__(self, address: str) -> None:
        self._address = address
        self._client: BleakClient | None = None
        self._buffer = PacketBuffer()
        self._queue: asyncio.Queue[Frame] = asyncio.Queue()

    async def __aenter__(self) -> "Recorder":
        self._client = BleakClient(self._address)
        await self._client.connect()
        await self._client.start_notify(NOTIFY_UUID, self._on_notify)
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client is not None:
            try:
                await self._client.stop_notify(NOTIFY_UUID)
            except Exception:
                pass
            await self._client.disconnect()

    def _on_notify(self, _char, data: bytearray) -> None:
        for frame in self._buffer.feed(bytes(data)):
            self._queue.put_nowait(frame)

    async def send(self, frame: bytes) -> None:
        assert self._client is not None
        await self._client.write_gatt_char(WRITE_UUID, frame, response=False)

    async def next_frame(self, timeout: float) -> Frame:
        return await asyncio.wait_for(self._queue.get(), timeout=timeout)

    async def request(self, frame: bytes, cmd_type: int, cmd_id: int, timeout: float,
                      what: str = "") -> Frame:
        """发命令，返回第一条类型和编号都对得上的回包；其余交给 other。"""
        await self.send(frame)
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise RecorderError(f"等待超时：{what}")
            reply = await self.next_frame(remaining)
            if reply.type == cmd_type and reply.id == cmd_id:
                return reply


@asynccontextmanager
async def find_and_open(address: str | None, serial: str | None, scan_timeout: float = 8.0):
    """选一颗录音豆并连上：给了 address 就连它；否则扫描选信号最强的。

    连上后若给了 serial，会由调用方核对（见 sync.py）。
    """
    if address is None:
        beans = await scan(scan_timeout)
        if not beans:
            raise NotFound("没找到录音豆（拿出充电盒并关掉手机飞书）")
        address = beans[0][0]
        log.info("附近录音豆 %s，选 %s", beans, address)
    async with Recorder(address) as recorder:
        yield recorder
