"""本地存储：录音段的音频、原始文字、纠错后文字和元数据。

数据都在本机，默认放 ~/.anker-xinlidou/（可用 ANKER_XINLIDOU_HOME 改）。
一个「录音段」对应录音豆上的一个文件，file_id 就是这段录音开始时的 Unix 时间戳（秒）。
"""

from __future__ import annotations

import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path


def home_dir() -> Path:
    env = os.environ.get("ANKER_XINLIDOU_HOME")
    base = Path(env).expanduser() if env else Path.home() / ".anker-xinlidou"
    return base


@dataclass
class Segment:
    file_id: int
    start_ts: int
    duration_ms: int
    audio_path: str | None
    raw_text: str | None
    corrected_text: str | None
    corrected: bool
    transcribed: bool

    @property
    def text(self) -> str | None:
        """对外优先给纠错版，没有就给原始版。"""
        return self.corrected_text or self.raw_text

    def to_dict(self) -> dict:
        end_ts = self.start_ts + self.duration_ms // 1000
        return {
            "id": self.file_id,
            "start": _iso(self.start_ts),
            "end": _iso(end_ts),
            "duration_seconds": round(self.duration_ms / 1000, 1),
            "text": self.text,
            "corrected": self.corrected,
            "transcribed": self.transcribed,
        }


def _iso(ts: int) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))


class Store:
    def __init__(self, base: Path | None = None) -> None:
        self.base = base or home_dir()
        self.audio_dir = self.base / "audio"
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.base / "db.sqlite3")
        self.db.row_factory = sqlite3.Row
        self._migrate()

    def _migrate(self) -> None:
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS segments (
                file_id      INTEGER PRIMARY KEY,
                start_ts     INTEGER NOT NULL,
                duration_ms  INTEGER NOT NULL,
                audio_path   TEXT,
                raw_text     TEXT,
                corrected_text TEXT,
                corrected    INTEGER NOT NULL DEFAULT 0,
                transcribed  INTEGER NOT NULL DEFAULT 0,
                created_at   INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_start ON segments(start_ts);
            """
        )
        self.db.commit()

    # --- 写 ---

    def has(self, file_id: int) -> bool:
        cur = self.db.execute("SELECT 1 FROM segments WHERE file_id=?", (file_id,))
        return cur.fetchone() is not None

    def add_audio(self, file_id: int, duration_ms: int, audio_path: str) -> None:
        self.db.execute(
            "INSERT OR IGNORE INTO segments(file_id,start_ts,duration_ms,audio_path,created_at) "
            "VALUES(?,?,?,?,?)",
            (file_id, file_id, duration_ms, audio_path, int(time.time())),
        )
        self.db.execute(
            "UPDATE segments SET duration_ms=?, audio_path=? WHERE file_id=?",
            (duration_ms, audio_path, file_id),
        )
        self.db.commit()

    def set_raw_text(self, file_id: int, text: str) -> None:
        self.db.execute(
            "UPDATE segments SET raw_text=?, transcribed=1 WHERE file_id=?", (text, file_id)
        )
        self.db.commit()

    def save_correction(self, file_id: int, text: str) -> None:
        self.db.execute(
            "UPDATE segments SET corrected_text=?, corrected=1 WHERE file_id=?", (text, file_id)
        )
        self.db.commit()

    # --- 读 ---

    def _row(self, r: sqlite3.Row) -> Segment:
        return Segment(
            file_id=r["file_id"], start_ts=r["start_ts"], duration_ms=r["duration_ms"],
            audio_path=r["audio_path"], raw_text=r["raw_text"], corrected_text=r["corrected_text"],
            corrected=bool(r["corrected"]), transcribed=bool(r["transcribed"]),
        )

    def get(self, file_id: int) -> Segment | None:
        r = self.db.execute("SELECT * FROM segments WHERE file_id=?", (file_id,)).fetchone()
        return self._row(r) if r else None

    def list_range(self, start_ts: int | None, end_ts: int | None, limit: int = 500) -> list[Segment]:
        q = "SELECT * FROM segments WHERE 1=1"
        args: list = []
        if start_ts is not None:
            q += " AND start_ts >= ?"
            args.append(start_ts)
        if end_ts is not None:
            q += " AND start_ts <= ?"
            args.append(end_ts)
        q += " ORDER BY start_ts ASC LIMIT ?"
        args.append(limit)
        return [self._row(r) for r in self.db.execute(q, args).fetchall()]

    def search(self, keyword: str, limit: int = 100) -> list[Segment]:
        like = f"%{keyword}%"
        rows = self.db.execute(
            "SELECT * FROM segments WHERE corrected_text LIKE ? OR raw_text LIKE ? "
            "ORDER BY start_ts ASC LIMIT ?",
            (like, like, limit),
        ).fetchall()
        return [self._row(r) for r in rows]

    def pending_transcription(self) -> list[Segment]:
        rows = self.db.execute(
            "SELECT * FROM segments WHERE transcribed=0 AND audio_path IS NOT NULL ORDER BY start_ts"
        ).fetchall()
        return [self._row(r) for r in rows]

    def pending_correction(self) -> list[Segment]:
        rows = self.db.execute(
            "SELECT * FROM segments WHERE transcribed=1 AND corrected=0 ORDER BY start_ts"
        ).fetchall()
        return [self._row(r) for r in rows]

    def latest_file_id(self) -> int | None:
        r = self.db.execute("SELECT MAX(file_id) AS m FROM segments").fetchone()
        return r["m"] if r and r["m"] is not None else None

    def close(self) -> None:
        self.db.close()
