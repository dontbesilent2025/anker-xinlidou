# Anker 心力豆

用手头的**安克 AI 录音豆**(soundcore Work / D3200,含飞书版),实现类似「全天候 AI 记录」的效果:录音豆别在身上录一天,回到电脑旁用蓝牙把录音同步下来、在**本机**转成文字,你的 **Agent**(Claude Code、Codex 等)通过 **MCP** 就能拉取、搜索这些内容。

**只要硬件 + MCP,不做 App,不搭服务器,数据全在你自己电脑上。**

> ⚠️ 非官方项目,与安克、飞书、OPPO 无关联。仅用于操作你**自己拥有**的设备。请先读 [DISCLAIMER.md](DISCLAIMER.md)。

## 和 OPPO 心力球的区别

| | OPPO 心力球 | Anker 心力豆(本项目) |
|---|---|---|
| 同步 | 手机全天实时 | 回电脑旁用蓝牙同步(**有延迟,拉不到当天在外的新内容**) |
| 转文字 | OPPO 云 | 本机 whisper(免费、不出网)或你自己的云端 Key |
| 数据 | OPPO 云 + 端 | 全在你自己电脑 |
| 取用 | OPPO App / MCP | 你的 Agent 通过本项目的 MCP |

这是用现成硬件换一个「数据自己掌握、不依赖厂商云」的方案,代价是同步不实时。

## 工作流程

```
录音豆(按键录一天) ──蓝牙──▶ 本机同步+解密 ──▶ whisper 转文字 ──▶ Agent 照术语表纠错 ──▶ MCP 供 Agent 取/搜
```

## 安装

需要 Python 3.10+、[ffmpeg](https://ffmpeg.org/)。本机转写还需 [whisper.cpp](https://github.com/ggml-org/whisper.cpp)。

```bash
pip install "anker-xinlidou @ git+https://github.com/<your>/anker-xinlidou.git"
```

本机转写(推荐,免费、音频不出电脑):装 whisper.cpp,下一个模型(中文建议 `ggml-large-v3-turbo`,约 1.6 GB),在 `~/.anker-xinlidou/config.json` 的 `transcribe` 里填 `model_path`。不想本机转的,把 `backend` 改 `cloud`,在环境变量 `ANKER_XINLIDOU_CLOUD_KEY` 放 Key(音频会上传到你填的服务)。

## 用法

```bash
anker-xinlidou scan     # 扫描附近的录音豆（关掉手机飞书，录音豆同时只连一台）
anker-xinlidou sync     # 把新录音拉下来并转写；首次会记住你的录音豆序列号
anker-xinlidou status   # 看配置和统计
```

日常:每天按录音豆的录音键开始录,回到电脑旁跑 `sync`,或让 Agent 调 MCP 的 `sync_now`。

## 接入 Agent（MCP）

启动 MCP server:

```bash
anker-xinlidou-mcp
```

在支持 MCP 的客户端里把它配成一个 stdio server(命令 `anker-xinlidou-mcp`)。工具:

| 工具 | 作用 |
|---|---|
| `sync_now` | 连录音豆、拉新录音、转文字 |
| `list_segments` | 按时间段列录音 |
| `get_transcript` | 取某段完整文字 |
| `search` | 按关键词搜 |
| `pending_corrections` | 列待纠错的段(带原始文字、术语表、纠错规则) |
| `save_correction` | 写回纠错后的文字 |
| `correction_guide` / `glossary` / `set_glossary` | 纠错规则与术语表 |

### 纠错由 Agent 做

语音识别总有错。本项目**不**在服务端跑大模型纠错(保持「不搭服务器」),而是让调用 MCP 的 Agent 纠:

1. Agent 调 `pending_corrections` → 拿到原始文字 + 术语表 + 纠错规则。
2. Agent **只纠识别错误**(同音字、听错的词、空格、按术语表改专名),**不改写、不润色、不总结**。
3. Agent 调 `save_correction` 写回。以后再读、再搜都是干净版。

**术语表**(`~/.anker-xinlidou/glossary.txt`)是纠错质量的命门:把人名、产品名、黑话的正确写法列进去,Agent 照着改。Whisper 对专名几乎必错,这一个文件比换更大的模型都管用。

## macOS 蓝牙权限（重要）

macOS 要求使用蓝牙的程序先获授权。**请在你自己的「终端」App 里运行本工具**:第一次跑 `scan` / `sync` 时,系统会弹窗「是否允许『终端』使用蓝牙」,点**允许**即可。

没有授权的进程一碰蓝牙会被系统**直接杀掉**(表现为程序闪退),这不是本工具的 bug,而是 macOS 的隐私机制。所以不要在没有蓝牙权限的后台环境里跑同步。授权一次后长期有效。

## 边界

- 不删除录音豆上的录音,不解绑飞书,不发送绑定/恢复出厂/升级固件等命令。
- 同步时手机飞书要断开(录音豆同时只连一台)。
- 开头约 1–2 秒的录音可能缺失(设备行为)。
- 本机临时的做法不替代你对自己设备和授权范围的确认。

## 数据位置

都在 `~/.anker-xinlidou/`(可用环境变量 `ANKER_XINLIDOU_HOME` 改):`db.sqlite3`、`audio/`、`config.json`、`glossary.txt`。

## 许可

[MIT](LICENSE)。协议来源与致谢见 [THIRD_PARTY.md](THIRD_PARTY.md)。
