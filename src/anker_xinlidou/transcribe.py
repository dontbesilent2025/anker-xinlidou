"""把录音段的 Ogg 音频转成文字。

默认用本机 whisper.cpp（免费、音频不出本机）。也可切到 OpenAI 兼容的云端服务，
此时音频会上传到你填的那个服务——第一次用前 MCP / CLI 会让你确认。

这里只产出「原始文字」。纠错由调用 MCP 的 Agent 做，见 docs 和术语表。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path

from .config import TranscribeConfig


class TranscribeError(Exception):
    pass


class NotConfigured(TranscribeError):
    """本机没装 whisper，也没配云端。Agent 应提示用户二选一。"""


def _find_whisper(cfg: TranscribeConfig) -> str | None:
    if cfg.whisper_bin and Path(cfg.whisper_bin).exists():
        return cfg.whisper_bin
    for name in ("whisper-cli", "whisper-cpp", "whisper"):
        found = shutil.which(name)
        if found:
            return found
    return None


def local_available(cfg: TranscribeConfig) -> bool:
    return _find_whisper(cfg) is not None and bool(cfg.model_path) and Path(cfg.model_path).exists()


def _ogg_to_wav16k(ogg_path: str) -> str:
    """whisper.cpp 要 16 kHz 单声道 WAV；用 ffmpeg 转。"""
    if not shutil.which("ffmpeg"):
        raise TranscribeError("需要 ffmpeg 把音频转成 whisper 能读的格式")
    wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", ogg_path, "-ac", "1", "-ar", "16000", wav],
        check=True,
    )
    return wav


def _transcribe_local(ogg_path: str, cfg: TranscribeConfig) -> str:
    binary = _find_whisper(cfg)
    if not binary:
        raise NotConfigured("本机没找到 whisper.cpp")
    if not cfg.model_path or not Path(cfg.model_path).exists():
        raise NotConfigured("没有配置 whisper 模型文件")
    wav = _ogg_to_wav16k(ogg_path)
    out_prefix = tempfile.mktemp()
    try:
        subprocess.run(
            [binary, "-m", cfg.model_path, "-f", wav, "-l", cfg.language or "auto",
             "-otxt", "-of", out_prefix, "-np"],
            check=True, capture_output=True,
        )
        txt = Path(out_prefix + ".txt")
        return txt.read_text("utf-8").strip() if txt.exists() else ""
    finally:
        for p in (wav, out_prefix + ".txt"):
            try:
                os.unlink(p)
            except OSError:
                pass


def _transcribe_cloud(ogg_path: str, cfg: TranscribeConfig) -> str:
    key = os.environ.get(cfg.cloud_key_env, "")
    if not key:
        raise NotConfigured(f"云端转写需要在环境变量 {cfg.cloud_key_env} 里放 API Key")
    url = cfg.cloud_base_url.rstrip("/") + "/audio/transcriptions"
    boundary = "----ankerxinlidou"
    with open(ogg_path, "rb") as f:
        audio = f.read()
    body = bytearray()
    for name, value in (("model", cfg.cloud_model), ("response_format", "text")):
        body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode())
    body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"audio.ogg\"\r\n".encode())
    body.extend(b"Content-Type: audio/ogg\r\n\r\n")
    body.extend(audio)
    body.extend(f"\r\n--{boundary}--\r\n".encode())
    req = urllib.request.Request(
        url, data=bytes(body),
        headers={"Authorization": f"Bearer {key}", "Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        raw = resp.read().decode("utf-8").strip()
    try:
        return json.loads(raw).get("text", raw)
    except json.JSONDecodeError:
        return raw


def transcribe(ogg_path: str, cfg: TranscribeConfig) -> str:
    if cfg.backend == "cloud":
        return _transcribe_cloud(ogg_path, cfg)
    return _transcribe_local(ogg_path, cfg)
