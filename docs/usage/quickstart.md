# BHD Memory Quickstart

## 1. 配置本机 Qdrant

一键启动：

```bash
./start.sh
```

脚本会检查本机 Qdrant、初始化 SQLite schema 和 Qdrant collection，并启动 Web UI。默认地址是 `http://127.0.0.1:8767`。

Web UI 使用 React + Vite。`./start.sh`
会在构建产物缺失或前端源码更新时自动构建。手动构建：

```bash
cd frontend
npm install
npm run build
```

默认配置：

```bash
export BHD_QDRANT_URL=http://127.0.0.1:6333
export BHD_QDRANT_COLLECTION=bhd_memory
```

可选配置：

```bash
export BHD_DB_PATH=.bhd/bhd.sqlite
export BHD_DATA_DIR=.bhd
export BHD_EMBEDDING_DIM=384
```

初始化 SQLite schema 与 Qdrant collection：

```bash
uv run bhd-memory init
```

## 2. 启动 API

```bash
uv run bhd-memory serve --host 127.0.0.1 --port 8767
```

Web 管理界面：

```text
http://127.0.0.1:8767/
```

健康检查：

```bash
curl http://127.0.0.1:8767/health
```

## 3. Dream 扫描与 Commit

显式扫描 JSONL transcript：

```bash
uv run bhd-memory dream-scan ./example-session.jsonl --auto-commit
```

异步扫描：

```bash
uv run bhd-memory dream-scan ./example-session.jsonl --auto-commit --enqueue
uv run bhd-memory worker
```

不传路径时会尝试扫描：

- `~/.claude/projects/**/*.jsonl`
- `~/.codex/sessions/**/*.jsonl`
- `~/.codex/conversations/**/*.jsonl`

也可以通过环境变量指定目录：

```bash
export BHD_CLAUDE_TRANSCRIPT_DIRS=/path/to/claude/logs
export BHD_CODEX_TRANSCRIPT_DIRS=/path/to/codex/logs
```

手动 commit：

```bash
uv run bhd-memory dream-commit <session_id>
```

提交 idle session：

```bash
uv run bhd-memory dream-sweep --idle-seconds 1800
```

持续轮询 transcript、提交 idle session 并执行队列：

```bash
uv run bhd-memory watch --idle-seconds 1800 --interval 60
```

对显式 transcript 路径做一次 watcher 流程：

```bash
uv run bhd-memory watch ./example-session.jsonl --once --idle-seconds 0
```

读取 archive：

```bash
curl http://127.0.0.1:8767/api/dream/sessions/<session_id>/archive/1
```

## 4. 知识上传

CLI 上传文件：

```bash
uv run bhd-memory upload-file ./docs/design/personal-memory-kb-system-design.md \
  --workspace-name bhd
```

API 上传文件：

```bash
curl -X POST http://127.0.0.1:8767/api/resources/upload \
  -F file=@./docs/design/personal-memory-kb-system-design.md \
  -F workspace_name=bhd
```

API 上传文本：

```bash
curl -X POST http://127.0.0.1:8767/api/resources/text \
  -H 'content-type: application/json' \
  -d '{"title":"Search Note","text":"Qdrant dense sparse hybrid retrieval is the main path."}'
```

异步上传文本：

```bash
curl -X POST http://127.0.0.1:8767/api/resources/text \
  -H 'content-type: application/json' \
  -d '{"title":"Queued Search Note","text":"Parse and index through the worker.","enqueue":true}'

curl -X POST http://127.0.0.1:8767/api/jobs/run-until-idle
```

抓取 URL 并索引：

```bash
uv run bhd-memory upload-url https://example.com/note.html --workspace-name bhd
```

或使用 API：

```bash
curl -X POST http://127.0.0.1:8767/api/resources/link \
  -H 'content-type: application/json' \
  -d '{"url":"https://example.com/note.html","workspace_name":"bhd"}'
```

## 5. 记忆治理

新增记忆：

```bash
curl -X POST http://127.0.0.1:8767/api/memories \
  -H 'content-type: application/json' \
  -d '{"content":"用户偏好中文回复。","scope":"global","category":"preference"}'
```

搜索记忆：

```bash
curl -X POST http://127.0.0.1:8767/api/memories/search \
  -H 'content-type: application/json' \
  -d '{"query":"中文回复","limit":5}'
```

软删除记忆：

```bash
curl -X DELETE http://127.0.0.1:8767/api/memories/<memory_id>
```

查看证据：

```bash
curl http://127.0.0.1:8767/api/memories/<memory_id>/evidence
```

查看 operation diff：

```bash
curl http://127.0.0.1:8767/api/memories/operations
```

审核 pending/conflict 记忆：

```bash
curl http://127.0.0.1:8767/api/memories/review
curl -X POST http://127.0.0.1:8767/api/memories/<memory_id>/approve
curl -X POST http://127.0.0.1:8767/api/memories/<memory_id>/reject
```

## 6. 统一检索

同时检索 memory 与 resource：

```bash
curl -X POST http://127.0.0.1:8767/api/retrieve \
  -H 'content-type: application/json' \
  -d '{"query":"hybrid retrieval","target_types":["memory","resource"],"limit":10}'
```

返回结果会包含：

- `type`: `memory` 或 `resource`
- `content`: 可注入上下文的内容
- `score` / `score_details`: Qdrant hybrid 分数信息
- `source`: 文件、会话或 memory 来源
- `evidence`: turn、chunk、artifact 等证据引用
- `load_more_uri`: 后续读取 L2 原文的稳定 URI

## 7. Hook / Recall

Hook 入口适合 Claude Code、Codex 或其它工具实时写入和召回上下文。通用 CLI：

```bash
uv run bhd-memory hook-capture \
  --source-app codex_hook \
  --session-id cx-123 \
  --role user \
  --content "请记住：当前项目测试命令是 uv run --extra dev pytest -q。" \
  --project-path "$PWD"

uv run bhd-memory hook-recall "当前项目测试命令" \
  --source-app codex_hook \
  --session-id cx-123

uv run bhd-memory hook-commit \
  --source-app codex_hook \
  --session-id cx-123 \
  --reason precompact
```

REST API：

```bash
curl -X POST http://127.0.0.1:8767/api/hooks/capture \
  -H 'content-type: application/json' \
  -d '{"source_app":"codex_hook","external_session_id":"cx-123","role":"user","content":"请记住：当前项目测试命令是 uv run --extra dev pytest -q。"}'

curl -X POST http://127.0.0.1:8767/api/hooks/recall \
  -H 'content-type: application/json' \
  -d '{"source_app":"codex_hook","external_session_id":"cx-123","query":"测试命令","target_types":["memory"]}'
```

通用 wrapper 示例在 `examples/hooks/`。

Codex / Claude Code 插件样板见 [plugins.md](plugins.md)。

## 8. Agentic Knowledge Tools

列出知识：

```bash
uv run bhd-memory knowledge-list
curl http://127.0.0.1:8767/api/knowledge/list
```

查看资源或 chunk：

```bash
uv run bhd-memory knowledge-view <resource_id>
curl http://127.0.0.1:8767/api/knowledge/view/<resource_id>
```

grep 文档：

```bash
uv run bhd-memory knowledge-grep "Qdrant|SQLite"
curl -X POST http://127.0.0.1:8767/api/knowledge/grep \
  -H 'content-type: application/json' \
  -d '{"pattern":"Qdrant|SQLite","limit":20}'
```

只查询知识库：

```bash
uv run bhd-memory knowledge-query "hybrid retrieval"
curl -X POST http://127.0.0.1:8767/api/knowledge/query \
  -H 'content-type: application/json' \
  -d '{"query":"hybrid retrieval","limit":5}'
```

资源 ACL：

```bash
uv run bhd-memory resource-acl <resource_id> \
  --grant --subject-type agent --subject-id codex --permission read

curl -X POST http://127.0.0.1:8767/api/resources/<resource_id>/acl \
  -H 'content-type: application/json' \
  -d '{"subject_type":"agent","subject_id":"codex","permission":"read"}'
```

## 9. 后台任务

列出任务：

```bash
uv run bhd-memory jobs
curl http://127.0.0.1:8767/api/jobs
```

运行一个任务：

```bash
uv run bhd-memory worker --once
curl -X POST http://127.0.0.1:8767/api/jobs/run-next
```

运行到队列为空：

```bash
uv run bhd-memory worker
curl -X POST http://127.0.0.1:8767/api/jobs/run-until-idle
```

## 10. 重建 Qdrant 索引

当 Qdrant collection 损坏、漂移或切换 embedding 维度后，可以从 SQLite 真源重建：

```bash
uv run bhd-memory rebuild-index --clear
```

API：

```bash
curl -X POST http://127.0.0.1:8767/api/index/rebuild \
  -H 'content-type: application/json' \
  -d '{"clear":true}'
```

异步重建：

```bash
curl -X POST http://127.0.0.1:8767/api/index/rebuild \
  -H 'content-type: application/json' \
  -d '{"clear":true,"enqueue":true}'
```

## 11. LLM Observer

默认使用规则型 Dream observer；如果要启用 OpenAI-compatible LLM 抽取：

```bash
export BHD_MEMORY_OBSERVER=hybrid
export BHD_LLM_BASE_URL=http://127.0.0.1:11434/v1
export BHD_LLM_MODEL=qwen2.5
export BHD_LLM_API_KEY=optional
```

`BHD_MEMORY_OBSERVER` 可选：

- `rule`: 只用本地规则。
- `llm`: 只用 LLM，失败时回到规则。
- `hybrid`: LLM 候选优先，再合并规则候选。

敏感、低置信度、冲突候选不会自动 active，会进入 review queue。

批准 conflict 记忆时，系统会把相关旧 active memory 标记为 `archived`，写入 `invalid_at`，并建立 `supersedes` relation。关系可通过：

```bash
curl http://127.0.0.1:8767/api/memories/<memory_id>/relations
```

图谱层和 Graphiti-compatible 同步见 [graph.md](graph.md)。
