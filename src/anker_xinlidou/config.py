"""一次性配置：记住你的录音豆序列号、转写方式。存成 ~/.anker-xinlidou/config.json。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .store import home_dir


@dataclass
class TranscribeConfig:
    # backend: "local"（本机 whisper.cpp，免费、不出网）或 "cloud"（你自己的 OpenAI 兼容服务）
    backend: str = "local"
    # 本机
    whisper_bin: str = ""          # whisper-cli / whisper-cpp 可执行文件；留空则 PATH 里找
    model_path: str = ""           # ggml / gguf 模型文件
    language: str = "auto"
    # 云端（可选）；api_key 建议用环境变量 ANKER_XINLIDOU_CLOUD_KEY，不写进文件
    cloud_base_url: str = "https://api.openai.com/v1"
    cloud_model: str = "whisper-1"
    cloud_key_env: str = "ANKER_XINLIDOU_CLOUD_KEY"


@dataclass
class Config:
    bean_address: str = ""         # 上次连到的录音豆蓝牙地址（优先连它）
    bean_serial: str = ""          # 你的录音豆序列号（认它、跳过别人的）
    transcribe: TranscribeConfig = field(default_factory=TranscribeConfig)

    @classmethod
    def load(cls, base: Path | None = None) -> "Config":
        path = (base or home_dir()) / "config.json"
        if not path.exists():
            return cls()
        data = json.loads(path.read_text("utf-8"))
        tc = TranscribeConfig(**data.pop("transcribe", {}))
        return cls(transcribe=tc, **data)

    def save(self, base: Path | None = None) -> None:
        d = (base or home_dir())
        d.mkdir(parents=True, exist_ok=True)
        (d / "config.json").write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2), "utf-8"
        )

    @property
    def configured_transcription(self) -> bool:
        tc = self.transcribe
        if tc.backend == "cloud":
            return bool(tc.cloud_base_url)
        return True  # 本机 whisper 由 transcribe 层按是否装了来判断
