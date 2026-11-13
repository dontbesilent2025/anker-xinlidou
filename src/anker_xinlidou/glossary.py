"""术语表和纠错指引。

术语表是用户自己维护的一个文本文件（人名、产品名、黑话），Agent 纠错前读它，
把 Whisper 容易听错的专有名词改对。这是纠错质量的命门。
"""

from __future__ import annotations

from pathlib import Path

from .store import home_dir

GLOSSARY_TEMPLATE = """\
# 术语表：每行一个词。Whisper 对人名、产品名、黑话几乎必错，
# 在这里列出正确写法，Agent 纠错时会照着改。可加注音或易错写法，用 = 分隔。
# 例：
# 泛直
# 栋哥
# 美女讲 AI = 美女讲爱、美女讲 I
"""

CORRECTION_GUIDE = """\
你在纠正语音转写（ASR）的识别错误。严格遵守：

只做：
- 改同音字、听错的词（根据上下文判断本意）。
- 按术语表把人名、产品名、黑话改成正确写法。
- 补中英文、中文与数字之间的空格；规范标点。

绝不做：
- 不改写、不润色、不让句子「更通顺」。
- 不删减、不合并、不补充没说过的内容。
- 不做总结、不提待办、不加标题。
- 拿不准本意时保留原文，不猜。

目标：和说话人原意逐字对应，只消除识别错误。改完用 save_correction 写回。
"""


def glossary_path() -> Path:
    return home_dir() / "glossary.txt"


def read_glossary() -> str:
    path = glossary_path()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(GLOSSARY_TEMPLATE, "utf-8")
    return path.read_text("utf-8")


def write_glossary(text: str) -> None:
    path = glossary_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, "utf-8")


def glossary_terms() -> list[str]:
    """只取有效词条（去掉注释和空行）。"""
    terms = []
    for line in read_glossary().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            terms.append(line)
    return terms
