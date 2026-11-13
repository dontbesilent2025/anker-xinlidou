"""命令行：scan（扫描附近录音豆）、sync（同步并转写）、status（看状态）。

全程只操作你自己的录音豆，不删除设备上的录音，不解绑飞书。
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from .config import Config
from .store import Store, home_dir


async def _scan() -> int:
    from .device import frames as F
    from .device.recorder import Recorder, scan

    beans = await scan(timeout=10.0)
    if not beans:
        print("没扫到录音豆。把它从充电盒拿出来，关掉手机上的飞书，再试。")
        return 1
    print(f"附近有 {len(beans)} 颗录音豆（讲录音豆协议的设备）：")
    for address, rssi in beans:
        line = f"- {address}  信号 {rssi}"
        try:
            async with Recorder(address) as rec:
                reply = await rec.request(F.get_device_info(), 0x01, 0x01, timeout=6, what="设备信息")
                info = F.DeviceInfo.parse(reply.payload)
                line += f"  序列号 {info.serial}  固件 {info.firmware}  电量 {info.battery_percent}%"
        except Exception as exc:
            line += f"  （读信息失败：{exc}）"
        print(line)
    return 0


async def _sync(args) -> int:
    from . import transcribe as T
    from .device import sync as syncmod

    store = Store()
    cfg = Config.load()

    def progress(done, total):
        print(f"\r拉取 {done}/{total}", end="", flush=True)

    try:
        result = await syncmod.sync(store, address=cfg.bean_address or None,
                                    serial=cfg.bean_serial or None, progress=progress)
    except syncmod.SerialMismatch as exc:
        print(f"\n跳过：{exc}")
        return 3
    print()
    if result.serial and not cfg.bean_serial:
        cfg.bean_serial = result.serial
        cfg.save()
        print(f"已认领这颗录音豆（序列号 {result.serial}），以后只认它。")
    print(f"设备：序列号 {result.serial} 固件 {result.firmware} 电量 {result.battery}%")
    print(f"新拉到 {len(result.new_segments)} 段，跳过已有 {result.skipped} 段。")
    for e in result.errors:
        print(f"  失败：{e}")

    pend = store.pending_transcription()
    if pend:
        print(f"转写 {len(pend)} 段…")
        done = 0
        for seg in pend:
            try:
                store.set_raw_text(seg.file_id, T.transcribe(seg.audio_path, cfg.transcribe))
                done += 1
                print(f"\r转写 {done}/{len(pend)}", end="", flush=True)
            except T.NotConfigured as exc:
                print(f"\n还没配置转写：{exc}")
                print("本机转写：装 whisper.cpp 并在 config.json 填 model_path；或切云端。见 README。")
                break
            except Exception as exc:
                print(f"\n  段 {seg.file_id} 转写失败：{exc}")
        print()
    print(f"待纠错 {len(store.pending_correction())} 段（让 Agent 通过 MCP 纠）。")
    store.close()
    return 0


def _status() -> int:
    cfg = Config.load()
    store = Store()
    total = len(store.list_range(None, None, limit=100000))
    print(f"存储目录：{home_dir()}")
    print(f"录音豆序列号：{cfg.bean_serial or '（还没认领，首次 sync 时记住）'}")
    print(f"转写方式：{cfg.transcribe.backend}")
    print(f"录音段：共 {total}，待转写 {len(store.pending_transcription())}，待纠错 {len(store.pending_correction())}")
    store.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="anker-xinlidou", description="用安克录音豆做全天候记录")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("scan", help="扫描附近的录音豆")
    sub.add_parser("sync", help="把新录音拉下来并转写")
    sub.add_parser("status", help="看配置和统计")
    sub.add_parser("mcp", help="启动 MCP server（供 Agent 连接）")
    args = parser.parse_args(argv)

    if args.cmd == "scan":
        return asyncio.run(_scan())
    if args.cmd == "sync":
        return asyncio.run(_sync(args))
    if args.cmd == "status":
        return _status()
    if args.cmd == "mcp":
        from .mcp_server import main as mcp_main
        mcp_main()
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
