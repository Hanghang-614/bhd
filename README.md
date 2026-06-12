# BHD Memory

[![CI](https://github.com/Hanghang-614/bhd/actions/workflows/ci.yml/badge.svg)](https://github.com/Hanghang-614/bhd/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

个人记忆 + 知识库系统。本项目按 `docs/design/personal-memory-kb-system-design.md`
实现本地优先的 MVP：

- Dream 入口：扫描 Claude Code / Codex / JSONL transcript，归档会话并抽取长期记忆。
- 知识入口：上传文本、URL、Markdown、HTML、PDF、DOCX、PPTX、XLSX 等文档，解析成 Resource / Node / Chunk。
- 统一检索：SQLite 保存事实、证据、operation diff；本机 Qdrant 保存 dense + sparse 向量索引。
- 治理接口：memory 支持 active / pending / paused / archived / deleted 状态、证据和访问日志。
- 后台队列：SQLite `ingest_job` + 本地 worker，支持 Dream、上传解析、重建索引异步执行。
- Review queue：低置信度、敏感信息、冲突记忆进入人工审核。
- Hook / recall：Claude、Codex 等工具可通过 CLI/API 实时 capture、recall、commit。
- Knowledge tools：list/view/grep/query 知识库，并记录 resource ACL。
- Graph truth layer：SQLite graph episode/entity/edge，支持 temporal supersedes 和 Graphiti-compatible sync。

## Quick Start

确保本机 Qdrant 已启动，默认地址为 `http://127.0.0.1:6333`。

```bash
./start.sh
```

或手动启动：

```bash
export BHD_QDRANT_URL=http://127.0.0.1:6333
export BHD_QDRANT_COLLECTION=bhd_memory

uv run bhd-memory init
uv run bhd-memory serve --port 8767
```

Web 管理界面：

```text
http://127.0.0.1:8767/
```

打开 API 健康检查：

```bash
curl http://127.0.0.1:8767/health
```

上传一段知识：

```bash
uv run bhd-memory upload-text "Architecture Note" \
  "Qdrant stores dense and sparse vectors. SQLite stores truth."
```

异步上传并执行队列：

```bash
uv run bhd-memory upload-text "Queued Note" "Parse me later." --enqueue
uv run bhd-memory worker
```

写入一条记忆：

```bash
curl -X POST http://127.0.0.1:8767/api/memories \
  -H 'content-type: application/json' \
  -d '{"content":"用户偏好先给结论再展开分析。","scope":"global","category":"preference"}'
```

统一检索：

```bash
curl -X POST http://127.0.0.1:8767/api/retrieve \
  -H 'content-type: application/json' \
  -d '{"query":"先给结论","target_types":["memory"],"limit":5}'
```

更多用法见 [docs/usage/quickstart.md](docs/usage/quickstart.md)。

## Installation

```bash
uv sync
uv run bhd-memory --help
```

作为本地命令使用：

```bash
uv tool install .
bhd-memory --help
```

## Development

```bash
uv sync --extra dev
uv run --extra dev pytest -q
uv run --extra dev ruff check .
```

测试默认使用 qdrant-client 的 `:memory:` 模式，不依赖外部 Qdrant 进程；实际运行默认连接本机 Qdrant。

## Documentation

- [Quickstart](docs/usage/quickstart.md)
- [Plugin hooks](docs/usage/plugins.md)
- [Graph memory](docs/usage/graph.md)
- [System design](docs/design/personal-memory-kb-system-design.md)

`research_repos/` 仅记录调研参考来源；外部仓库副本不随本项目发布。

## Contributing

欢迎提交 issue 和 pull request。开始前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。

## Security

如果你发现安全问题，请先阅读 [SECURITY.md](SECURITY.md)，不要直接公开敏感细节。

## License

本项目使用 [MIT License](LICENSE)。
