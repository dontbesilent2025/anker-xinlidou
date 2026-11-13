# 第三方来源与致谢

本项目的录音豆蓝牙协议实现,用 Python 独立编写,参考了以下公开资料。未复制任何固件或私钥。

## 协议研究（参考,未复制代码）

- **tacshi/Soundcore** — 从飞书安卓 App 内安克 SDK 整理出的 `PROTOCOL.md`,记录了 BLE 服务与特征、帧格式、会话密钥与音频解密流程。本项目据此理解协议。

## 逻辑参考（MIT）

- **knorthfield/soundcore-pull**(MIT)— Swift 实现的本地拉取工具。本项目的帧格式、校验、ECDH/HKDF 会话、AES-CTR 解密和 Ogg/Opus 封装,是对其同类逻辑的独立 Python 重写。
- **Shawn-TKD/recording-bean-web**(MIT,Copyright (c) 2026 Recording Bean Local contributors)— 浏览器端实现,交叉验证了同一套协议。

以上项目均声明为「与安克、飞书无关联,仅用于与自己拥有的硬件互操作」。本项目沿用同样的边界。

## 运行时依赖

- [bleak](https://github.com/hbldh/bleak)(MIT)— 跨平台 BLE。
- [cryptography](https://github.com/pyca/cryptography)(Apache-2.0 / BSD)— ECDH、HKDF、AES。
- [mcp](https://github.com/modelcontextprotocol/python-sdk)(MIT)— MCP server。
- 转写依赖 [ffmpeg](https://ffmpeg.org/) 与 [whisper.cpp](https://github.com/ggml-org/whisper.cpp)(本机,可选)。
