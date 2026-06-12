# Documentation

当前目录用于保存个人记忆 + 知识库系统的调研、方案和后续实现文档。

| Directory | Purpose |
|---|---|
| `design/` | 架构方案、系统设计、实现路线 |
| `research/` | 开源项目调研、技术选型分析、参考证据 |

## Main Documents

| Document | Description |
|---|---|
| [`design/personal-memory-kb-system-design.md`](design/personal-memory-kb-system-design.md) | 最终方案文档：架构、数据模型、Dream 入口、知识上传、Qdrant/SQLite 选型、MVP 路线 |
| [`design/dream-transcript-memory-solution.md`](design/dream-transcript-memory-solution.md) | Dream 专项方案：transcript 扫描、会话归档、长期记忆抽取、治理与后续路线 |
| [`design/memory-review-governance.md`](design/memory-review-governance.md) | 记忆审核与治理方案：低置信度、敏感信息、冲突记忆、人工审核队列与用户确认机制 |
| [`design/knowledge-ingest-implementation.md`](design/knowledge-ingest-implementation.md) | 知识入口实现说明：文本、URL、Markdown、HTML、PDF、Office 文档如何解析成 Resource / Node / Chunk 并索引 |
| [`research/personal-memory-kb-research.md`](research/personal-memory-kb-research.md) | 调研分析文档：mem0、OpenViking、Khoj、AnythingLLM 等项目参考 |
| [`usage/quickstart.md`](usage/quickstart.md) | 本地 Qdrant、CLI、API、Dream 扫描、知识上传与检索使用说明 |
| [`usage/unified-retrieval.md`](usage/unified-retrieval.md) | 统一检索实现说明：SQLite truth store + Qdrant dense/sparse index |
| [`usage/plugins.md`](usage/plugins.md) | Codex / Claude Code hook 插件样板说明 |
| [`usage/graph.md`](usage/graph.md) | 本地图谱、temporal supersedes 与 Graphiti-compatible 同步说明 |
