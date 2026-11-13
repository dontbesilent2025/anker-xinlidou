"""Anker 心力豆 的 MCP server：让 Agent 拉取、搜索录音豆录下的内容，并写回纠错。

工具一览：
- sync_now          连录音豆、把新录音拉下来并转成文字（原始版）
- list_segments     按时间段列出录音段
- get_transcript    取某段的完整文字
- search            按关键词搜
- pending_corrections  列出转写完、还没纠错的段（给 Agent 纠）
- save_correction   把纠错后的文字写回
- correction_guide  纠错规则（只纠识别错误，不改写）
- glossary / set_glossary  术语表（纠错时照它改专名）
"""

from __future__ import annotations

import time

try:
    from mcp.server.mcpserver import MCPServer as _Server  # mcp >= 2
except ModuleNotFoundError:  # pragma: no cover
    from mcp.server.fastmcp import FastMCP as _Server      # mcp < 2

from . import glossary as G
from . import transcribe as T
from .config import Config
from .store import Store

server = _Server("anker-xinlidou")


def _store() -> Store:
    return Store()


def _parse_ts(s: str | None) -> int | None:
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return int(time.mktime(time.strptime(s, fmt)))
        except ValueError:
            continue
    raise ValueError(f"时间格式看不懂：{s}（用 2026-11-13 或 2026-11-13 14:30）")


@server.tool(description="连录音豆、把还没拉过的录音整段取下来并转成文字（原始版）。用户需在电脑旁、关掉手机飞书。返回新增与待纠错数量。")
async def sync_now() -> dict:
    from .device import sync as syncmod  # 延迟导入，避免没装 bleak 时整个 server 起不来

    store = _store()
    cfg = Config.load()
    result = await syncmod.sync(store, address=cfg.bean_address or None,
                                serial=cfg.bean_serial or None)
    # 记住这颗录音豆
    if result.serial:
        cfg.bean_serial = result.serial
        cfg.save()

    transcribed, need_setup = 0, False
    for seg in store.pending_transcription():
        try:
            text = T.transcribe(seg.audio_path, cfg.transcribe)
            store.set_raw_text(seg.file_id, text)
            transcribed += 1
        except T.NotConfigured:
            need_setup = True
            break
        except Exception:
            continue

    out = {
        "device_serial": result.serial,
        "firmware": result.firmware,
        "battery_percent": result.battery,
        "new_recordings": len(result.new_segments),
        "skipped_existing": result.skipped,
        "transcribed": transcribed,
        "pending_correction": len(store.pending_correction()),
        "errors": result.errors,
    }
    if need_setup:
        out["transcription_not_configured"] = (
            "还没配置转写。两种选择，请问用户选哪个："
            "① 本机 whisper.cpp（免费、音频不出电脑，需装 whisper.cpp 并下一个模型，约 1.6 GB）；"
            "② 云端 API（在环境变量里放 Key，音频会上传到该服务，按量付费）。"
            "选定后让用户配 config.json 的 transcribe 段，再调一次 sync_now。"
        )
    store.close()
    return out


@server.tool(description="按时间段列出录音段。start/end 用 2026-11-13 或 2026-11-13 14:30，可只给一个或都不给。")
def list_segments(start: str | None = None, end: str | None = None, limit: int = 100) -> list[dict]:
    store = _store()
    segs = store.list_range(_parse_ts(start), _parse_ts(end), limit)
    store.close()
    return [s.to_dict() for s in segs]


@server.tool(description="取某一段录音的完整文字（优先纠错版，没纠错则原始版）。")
def get_transcript(segment_id: int) -> dict:
    store = _store()
    seg = store.get(segment_id)
    store.close()
    if not seg:
        return {"error": f"没有这段录音：{segment_id}"}
    return seg.to_dict()


@server.tool(description="按关键词搜录音文字，返回命中的段。")
def search(keyword: str, limit: int = 50) -> list[dict]:
    store = _store()
    segs = store.search(keyword, limit)
    store.close()
    return [s.to_dict() for s in segs]


@server.tool(description="列出已转写、还没纠错的段，给出原始文字供你纠正。纠正前先看 correction_guide 和 glossary。")
def pending_corrections(limit: int = 20) -> dict:
    store = _store()
    segs = store.pending_correction()[:limit]
    items = [{"id": s.file_id, "start": s.to_dict()["start"], "raw_text": s.raw_text} for s in segs]
    store.close()
    return {
        "guide": G.CORRECTION_GUIDE,
        "glossary": G.read_glossary(),
        "segments": items,
        "note": "逐段纠正后用 save_correction 写回。只纠识别错误，不改写。",
    }


@server.tool(description="把纠错后的文字写回某一段，标记为已纠错。只应写入纠正识别错误后的文字，不要改写内容。")
def save_correction(segment_id: int, corrected_text: str) -> dict:
    store = _store()
    if not store.get(segment_id):
        store.close()
        return {"error": f"没有这段录音：{segment_id}"}
    store.save_correction(segment_id, corrected_text)
    store.close()
    return {"ok": True, "id": segment_id}


@server.tool(description="纠错规则：只纠语音识别错误（同音字、听错的词、空格、专名），不改写、不润色、不总结。")
def correction_guide() -> str:
    return G.CORRECTION_GUIDE


@server.tool(description="读术语表（人名、产品名、黑话的正确写法），纠错时照它改专名。")
def glossary() -> str:
    return G.read_glossary()


@server.tool(description="更新术语表，整段覆盖。")
def set_glossary(text: str) -> dict:
    G.write_glossary(text)
    return {"ok": True}


def main() -> None:
    import anyio
    anyio.run(server.run_stdio_async)


if __name__ == "__main__":
    main()
