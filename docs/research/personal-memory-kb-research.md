# 个人记忆 + 知识库系统调研

调研日期：2026-06-08

## 1. 调研目标与结论摘要

本轮只做调研，不做实现。目标是为当前项目设计一个“个人记忆 + 知识库系统”，覆盖两个入口：

1. **记忆写入入口 Dream**：读取 Claude Code / Codex 对话记录，并预留其它对话源扩展能力；对会话进行分析、总结、抽取，形成长期记忆。
2. **知识上传入口**：用户上传任意格式文档，系统解析、切分、索引，并支持后续检索增强。

本次研究了 4 个开源项目：

| 项目 | 本地路径 | 上游仓库 | commit | 主要参考价值 |
|---|---|---|---|---|
| mem0 | `research_repos/mem0` | https://github.com/mem0ai/mem0.git | `36694596` | 事实型记忆抽取、ADD-only 写入、实体链接、混合检索、OpenMemory 治理层 |
| OpenViking | `research_repos/OpenViking` | https://github.com/volcengine/OpenViking.git | `58ff0290` | Resource/Memory/Skill 统一上下文库、L0/L1/L2 渐进加载、会话 commit 与 memory diff、Claude Code/Codex hook 经验 |
| Khoj | `research_repos/khoj` | https://github.com/khoj-ai/khoj.git | `9258f57` | 个人第二大脑产品、多端文档同步、增量文档索引、文件/日期/词过滤、简单可控 memory |
| AnythingLLM | `research_repos/anything-llm` | https://github.com/Mintplex-Labs/anything-llm.git | `c7790ce` | 文档 collector/server 分层、workspace 文档管理、向量缓存、pinned/watched 文档、全局/工作区记忆 |

核心结论：

1. **不要只做向量库**。长期可用的个人记忆系统需要原始证据、会话归档、记忆状态、diff、删除/暂停/回滚、来源与权限。
2. **Dream 应该采用“会话归档 -> 总结 -> 候选记忆 -> 反思/去重 -> 写入 diff”的异步流水线**。OpenViking 的 session commit 和 AnythingLLM 的 Observer/Reflector 两阶段值得组合。
3. **知识上传应采用“解析与语义分离”**。先把文档稳定解析成结构化文本与元数据，再异步生成摘要、embedding、关键词索引。OpenViking 和 AnythingLLM 都印证了这个边界。
4. **检索层应做混合召回**：语义向量 + BM25/关键词 + 实体/时间/来源过滤 + 可选 rerank。mem0 的多信号融合和 Khoj 的过滤体验都值得借鉴。
5. **当前项目建议采用统一上下文模型**：`Resource` 表示用户上传知识，`Memory` 表示从对话中抽取的长期记忆，后续可扩展 `Skill` 或 `Procedure` 表示可复用能力/工作流。

## 2. 参考项目选择说明

用户已提供本地 `research_repos/mem0` 和 `research_repos/OpenViking`。额外选择：

1. **Khoj**：定位为个人 AI second brain，文档同步、搜索、聊天、个人 memory、agent scoping 都贴近“个人知识库”。
2. **AnythingLLM**：成熟的“上传文档 -> 解析 -> workspace RAG -> 记忆个性化”产品，collector 分层、向量缓存、文档关系、全局/工作区记忆非常适合参考工程边界。

未选择但后续可补充研究：

| 项目 | 可补充价值 | 本轮未选原因 |
|---|---|---|
| Onyx/Danswer | 企业连接器、权限、搜索后台 | 偏企业知识库，个人记忆抽取弱 |
| LlamaIndex | 文档 parser/chunker/retriever 抽象 | 更像框架，不是完整产品实践 |
| Letta/MemGPT | Agent memory 分层理论 | 文档知识库上传链路弱 |
| Open WebUI | 用户聊天记忆与知识集合 | 重点在 Web UI/LLM 网关，文档 pipeline 不如 AnythingLLM 清楚 |

## 3. mem0 调研

### 3.1 架构与数据流

mem0 核心定位是“AI 的 memory layer”。本地 `research_repos/mem0/mem0/memory/main.py` 是主要实现入口：

```text
messages
  -> parse messages
  -> retrieve related existing memories
  -> LLM single-call extraction
  -> batch embedding
  -> hash dedup
  -> vector store insert
  -> SQLite history
  -> entity extraction/linking
```

关键实现点：

1. `Memory.add()` 要求至少有 `user_id` / `agent_id` / `run_id` 之一作为作用域。
2. `infer=True` 时，LLM 从消息中抽取 facts；`infer=False` 时按原文逐条写入。
3. v3 思路偏 **ADD-only**：不在主流程中让模型直接 UPDATE/DELETE 旧记忆，而是累积事实，并通过 hash 去重和检索融合解决召回。
4. 每条 memory payload 包含 `data`、`hash`、`created_at`、`updated_at`、`text_lemmatized`、作用域字段等。
5. history 使用 SQLite 记录 memory 变更。
6. 实体抽取后写入独立 entity store，entity payload 维护 `linked_memory_ids`。

### 3.2 检索实践

`Memory.search()` 的检索流程：

1. 校验作用域 filters，避免无边界检索。
2. query lemmatization，用于 BM25/关键词检索。
3. query entity extraction，用于实体 boost。
4. 向量语义检索 over-fetch，默认内部取 `max(top_k * 4, 60)`。
5. 如果 vector store 支持，执行 keyword search。
6. 计算 BM25 归一化分数。
7. 根据 query entities 到 entity store 搜索，给 linked memories 加 boost。
8. 通过 `score_and_rank` 融合语义、BM25、实体分数。
9. 可选 rerank。

这个设计对当前项目非常重要：个人记忆经常很短，纯向量检索容易漏掉人名、项目名、工具名；实体/关键词补充能显著提升可用性。

### 3.3 OpenMemory 治理层

mem0 仓库下的 `openmemory` 展示了产品化 memory 的治理需求：

1. `MemoryState`: `active` / `paused` / `archived` / `deleted`。
2. `User`、`App`、`Memory` 建模，把 memory 归属到用户和调用应用。
3. `MemoryStatusHistory` 记录状态变更。
4. `MemoryAccessLog` 记录检索访问。
5. `AccessControl` 和 app active 状态控制记忆是否可读写。
6. MCP server 暴露 `add_memories` / `search_memory` 等工具，并在写入时记录来源 app。

注意：OpenMemory 的 `search_memory` 示例中绕过了 mem0 的混合检索，直接使用 vector search 再做 ACL 过滤。这说明应用层接入时容易因为权限/产品逻辑而损失底层检索能力。当前项目应避免这种割裂：权限过滤和混合检索需要在统一 retrieval service 中完成。

### 3.4 借鉴点

当前项目应借鉴：

1. **事实型 memory schema**：memory 是一句或少数几句稳定事实，而不是整段对话摘要。
2. **ADD-first 写入策略**：首版优先追加和去重，避免模型错误覆盖旧事实。
3. **作用域强制**：所有 memory 必须带 `user_id`、`source_app`、`project/workspace`、`session_id` 等边界。
4. **hash dedup + batch embedding**：提升写入吞吐，降低重复。
5. **实体链接**：人名、项目名、工具名、文件名、组织名应成为一等检索信号。
6. **混合检索**：semantic + BM25 + entity boost + metadata filters。
7. **memory 状态与访问日志**：自动写入必须可暂停、删除、审计。

不建议直接照搬：

1. **只存短事实而不存证据**。Dream 从开发对话抽取记忆，必须保留原始会话证据和 turn 引用。
2. **完全 ADD-only 不处理冲突**。个人系统可以首版 ADD-only，但需要后续 conflict detection 和人工合并。
3. **只按 user/agent/run 三个字段作用域**。我们需要更丰富的 `source_app`、`project_path`、`repo`、`conversation_id`、`workspace_id`。

## 4. OpenViking 调研

### 4.1 统一上下文数据库

OpenViking 把上下文抽象为三类：

| 类型 | 作用 | 生命周期 | 典型来源 |
|---|---|---|---|
| Resource | 用户提供的知识、规则、文档 | 相对静态 | 文档上传、代码仓库、API docs |
| Memory | Agent 从互动中学到的长期认知 | 动态更新 | 对话、工具执行、会话总结 |
| Skill | 可调用能力或工作流 | 相对静态 | Skill、MCP、脚本 |

这与当前目标高度一致。建议当前项目首版落地 `Resource` 和 `Memory`，预留 `Skill/Procedure` 类型。

### 4.2 L0/L1/L2 渐进上下文

OpenViking 的三层信息模型：

| 层 | 内容 | 用途 |
|---|---|---|
| L0 Abstract | 约 100 tokens 的摘要 | 向量召回、快速判断 |
| L1 Overview | 约 1k-2k tokens 的结构化概览 | rerank、导航、构造 prompt |
| L2 Detail | 原文或完整文件 | 确认需要时按需读取 |

这个模型适合文档和会话归档：

1. 文档上传后，原文是 L2，章节/文档概览是 L1，短摘要是 L0。
2. Claude/Codex 会话归档后，完整 transcript 是 L2，会话总结是 L1，一句话主题是 L0。
3. 检索时先找 L0/L1，只有进入回答或推理阶段再加载 L2。

### 4.3 文档解析与语义分离

OpenViking 的添加 Resource 流程：

```text
Input File -> Parser -> TreeBuilder -> AGFS -> SemanticQueue -> Vector Index
```

关键原则：

1. Parser 不调用 LLM，只负责格式转换和结构化。
2. TreeBuilder 把临时目录移动到内容存储。
3. SemanticQueue 异步自底向上生成 L0/L1。
4. Vector Index 只存 URI、vector、metadata，不作为内容真源。

这对当前项目的知识上传入口非常关键：不要在上传请求里同步做昂贵 LLM 总结；上传应尽快返回 job，后台解析、摘要、向量化。

### 4.4 Session commit 与 memory diff

OpenViking 的 session 管理流程：

```text
session.add_message(...)
session.used(...)
session.commit()
  -> 同步归档 messages.jsonl
  -> 异步生成 summary
  -> 异步抽取 long-term memories
  -> 写 memory_diff.json
```

Memory extraction 中包含：

1. 8 类 memory：profile、preferences、entities、events、cases、patterns、tools、skills。
2. 候选 memory 与已有 memory 做向量预过滤。
3. LLM 决策 candidate skip/create/none，以及对已有 item merge/delete。
4. 每次 commit 写 `memory_diff.json`，包含 adds/updates/deletes，便于审计和回滚。

这几乎可以直接作为 Dream 的主流程参考：Dream 不是“从日志直接写 memory”，而是“会话归档后 commit，由后台抽取 memory，并保存 diff”。

### 4.5 Claude Code / Codex 插件经验

OpenViking 已有 Claude Code 和 Codex 插件：

1. Claude Code：SessionStart 注入 profile/index；每次 prompt 前 recall；每轮结束 capture；compaction/session end 前 commit；subagent 单独 session。
2. Codex：`UserPromptSubmit` recall，`Stop` 增量 capture，`PreCompact` deterministic commit；由于没有可靠 SessionEnd，使用 startup/clear active-window heuristic 和 idle TTL sweep 处理 orphan session。
3. 插件把 Codex session 映射为确定性 OpenViking session，例如 `cx-<codex_session_id>`。
4. Stop hook 只 append，不每轮 commit，避免过度碎片化。

当前项目的 Dream 入口首版是“读取本地对话记录”，不必立即做 hook 插件；但应借鉴它的生命周期判断：

1. **会话仍活跃时不要急于抽取**。
2. **compaction / idle / 手动结束**是更适合 commit 的时机。
3. **每个外部会话映射到稳定内部 session_id**。
4. **保留 cursor / capturedTurnCount**，支持增量读取。

### 4.6 借鉴点

当前项目应借鉴：

1. **Resource/Memory/Skill 统一上下文类型**。
2. **URI/路径化组织**：所有内容都有稳定引用，memory 可追溯到 session archive。
3. **L0/L1/L2 渐进加载**。
4. **解析与语义异步分离**。
5. **Session commit 作为 Dream 的抽取边界**。
6. **memory_diff 审计与回滚**。
7. **Claude/Codex 生命周期经验**：Stop 只捕获，PreCompact/idle 才提交。

不建议直接照搬：

1. **完整虚拟文件系统对 MVP 可能偏重**。可先用数据库表 + 文件对象存储模拟 URI。
2. **8 类 memory 首版不必全部复杂实现**。建议先落 5 类：profile、preferences、entities、events、procedures/lessons。
3. **层级检索可以分阶段实现**。首版先统一 chunk/doc/memory 检索，后续再做目录级递归。

## 5. Khoj 调研

### 5.1 产品形态

Khoj 是个人 AI second brain，支持：

1. Web、Desktop、Obsidian、Emacs、WhatsApp 等多端入口。
2. PDF、Markdown、Notion、Word、org-mode、图片等数据源。
3. 文档语义搜索、chat with docs、agent、automation。
4. 用户/agent 维度的 memory 开关和作用域。

它对当前项目的启发是：个人知识库不是只有 API 和检索，还需要低摩擦导入、同步、来源定位、用户可控开关。

### 5.2 文档解析与增量索引

Khoj 的 `TextToEntries` 抽象把文档处理成 Entry，并执行：

1. 结构化抽取：Markdown 按 heading 递归拆分，PDF 按页抽取，DOCX 用 loader 抽文本。
2. chunk fallback：超过 max tokens 后用 `RecursiveCharacterTextSplitter` 按段落、句子、词、字符逐级切分。
3. 每个 chunk 保留：
   - `compiled`：带文件名/heading 的索引文本。
   - `raw`：原始片段。
   - `heading`：标题上下文。
   - `file`：文件路径。
   - `uri`：例如 `file://...#line=...`。
   - `corpus_id`：同一原始 entry 分裂出的 chunks 共享 corpus id。
4. hash 去重：按 entry 内容 hash 判断新增/更新/删除。
5. 保存文件原文对象，方便后续定位和完整读取。
6. 从 entry 中抽取日期，支持日期过滤。

### 5.3 搜索与过滤

Khoj 的搜索链路：

1. bi-encoder 为文档 chunk 和 query 生成 embedding。
2. pgvector 的 cosine distance 做召回。
3. 支持 file filter、word filter、date filter。
4. 可用 cross-encoder rerank。
5. 结果去重：按 hash 或 corpus_id 避免同一内容重复出现。

这说明“个人知识库检索体验”里过滤非常重要。用户经常会问“某个文件里”、“最近”、“包含某个词但排除某目录”的问题，不能只靠 embedding。

### 5.4 memory 实践

Khoj 的 `UserMemory` 相对简单：

1. memory 存 raw 文本和 embedding。
2. 支持保存、搜索、删除、更新。
3. memory 可按 user + agent scoped。
4. memory 开关由 server mode 和 user preference 共同决定：
   - disabled
   - enabled default off
   - enabled default on
5. default agent 可访问用户所有 memory，非 default agent 只访问自己的 memory。

这个模型比 mem0 简单，但产品控制做得好：用户必须能看到、改、删自己的 memory。

### 5.5 借鉴点

当前项目应借鉴：

1. **Entry 模型**：`raw`、`compiled`、`heading`、`file`、`uri` 分离。
2. **结构优先切分**：Markdown/HTML/代码按 heading/AST/page，超过 token 限制再递归切分。
3. **增量索引**：文件/entry hash，删除不存在的旧 chunks。
4. **源码定位**：行号、页码、URL、source path 必须保留。
5. **过滤能力**：file/date/word filters 是个人知识库基础能力。
6. **用户可控 memory 设置**：全局默认 + 用户 opt-in/opt-out。

不建议直接照搬：

1. **固定 256-token chunk 太小**。开发对话、设计文档可使用 500-1200 token，并按类型配置。
2. **memory 抽取较轻**。Dream 需要更强的会话总结、证据、dedup、状态管理。
3. **文档结构层次不够丰富**。当前项目应结合 OpenViking 的 L0/L1/L2。

## 6. AnythingLLM 调研

### 6.1 collector/server 分层

AnythingLLM monorepo 中：

1. `collector` 负责接收上传、解析文件/链接/raw text，并写入 server documents 文件夹。
2. `server` 负责 workspace、文档关系、向量库、LLM、聊天、memory 等。
3. collector 输出 JSON document，核心字段是 `pageContent`，其它字段作为 metadata。

典型 document JSON：

```json
{
  "id": "...",
  "url": "file:///path/to/file.pdf",
  "title": "file.pdf",
  "docAuthor": "no author found",
  "description": "No description found.",
  "docSource": "pdf file uploaded by the user.",
  "chunkSource": "",
  "published": "...",
  "wordCount": 1234,
  "pageContent": "...",
  "token_count_estimate": 1800
}
```

这个边界很清楚：解析产物是“ready-to-embed document”，而不是直接写向量库。

### 6.2 任意格式解析实践

AnythingLLM 的 `processSingleFile`：

1. 规范化路径，防止 path traversal。
2. 检查保留文件名、文件存在性、扩展名。
3. 如果扩展名没有显式 converter，但 MIME/内容看起来是文本，则 fallback 为 `.txt`。
4. 不支持且不是文本时失败并清理上传文件。
5. 根据扩展名调用 converter。

解析器实践：

1. PDF：先 `PDFLoader` 按页抽取；无文本时用 OCR fallback。
2. DOCX：使用 LangChain DocxLoader。
3. Office-like：使用 `officeparser`。
4. Raw text：标准化 metadata 后写入 JSON。
5. Audio/image/video 等有独立扩展路径。

### 6.3 文档向量化与缓存

默认 LanceDB provider 的 `addDocumentToNamespace`：

1. `pageContent` 与 metadata 分离。
2. 检查 vector-cache，已有缓存时可直接复用 embedding 结果。
3. 使用 `TextSplitter` 根据 embedder 限制确定 chunk size。
4. 每个 chunk 前可插入 `<document_metadata>`，包含 title、published、source 等。
5. 生成 embeddings 后写入向量库，同时在关系表 `document_vectors` 中记录 `docId -> vectorId`。
6. 删除文档时通过 `docId` 找到所有 vectorId 并删除。

这对当前项目非常有价值：文档原始记录、chunk vectors、workspace 文档关系必须解耦；不要只把向量写进去却无法按文档删除。

### 6.4 workspace 文档管理

AnythingLLM 的 `workspace_documents` 维护：

1. `docId`：文档唯一 ID。
2. `docpath`：collector 输出 JSON 的路径。
3. `workspaceId`：文档属于哪个 workspace。
4. `metadata`：JSON 字符串。
5. `pinned`：被 pin 的文档会被完整加入上下文。
6. `watched`：可定期 resync。

DocumentManager 会把 pinned documents 直接读出并按 token budget 前置到上下文；向量检索时会过滤掉已 pinned 的重复 sources。

### 6.5 memory 自动抽取

AnythingLLM 的 memory job 非常适合 Dream 借鉴：

1. 找出 `memoryProcessed` 为空的 chat。
2. 按 `(user_id, workspaceId)` 分组。
3. 至少 5 条聊天才处理，且 20 分钟 idle 后才处理，避免活跃会话被过早总结。
4. 每次最多看 20 条聊天，每条 prompt/response 截断到 1500 字符，控制成本。
5. Observer 阶段抽候选事实，最多 3 条，带 confidence 和 reasoning。
6. Reflector 阶段结合现有 GLOBAL / WORKSPACE memories 去重、过滤、分类、更新。
7. memory scope 分为：
   - GLOBAL：跨 workspace 都有用，如姓名、长期偏好、职业角色。
   - WORKSPACE：项目内事实，如当前项目目标、局部偏好。
8. GLOBAL 默认上限 5，WORKSPACE 默认上限 20。
9. 用户可以手动增删改 memory，也可以 promote/demote global/workspace。

### 6.6 借鉴点

当前项目应借鉴：

1. **collector/server 分层**：解析服务独立，server 负责索引和治理。
2. **document JSON 中间层**：解析产物可审计、可重试、可重新向量化。
3. **MIME + 文本 fallback + OCR fallback**。
4. **workspace 文档关系**：同一文档可属于不同项目/空间。
5. **docId -> vectorId 映射**：支持文档级删除、重建、同步。
6. **vector-cache**：避免重复嵌入成本。
7. **GLOBAL / WORKSPACE memory 分层**。
8. **Observer/Reflector 两阶段 memory 写入**。
9. **idle 后处理，避免活跃会话中途写入**。
10. **memory 容量上限和人工 promote/demote**。

不建议直接照搬：

1. **GLOBAL=5 上限过小**。个人系统可采用软上限 + 分层摘要，而不是硬限制太低。
2. **memory 不做向量/实体检索融合**。AnythingLLM memory 偏 prompt 注入，当前项目应结合 mem0 的混合检索。
3. **collector 输出单个大 pageContent 后再统一 chunk**。对 Markdown/代码/长 PDF，应更早保留结构层次。

## 7. 横向对比

### 7.1 记忆写入

| 维度 | mem0 | OpenViking | Khoj | AnythingLLM | 当前项目建议 |
|---|---|---|---|---|---|
| 写入触发 | API add | session commit | 手动/聊天流程 | idle job | Dream 定期扫描 + 手动/idle/compact commit |
| 输入 | messages/facts | session messages | raw memory | workspace chats | normalized transcript |
| 抽取 | 单 LLM call ADD-only | LLM extract + dedup decision | 简单保存 | Observer/Reflector | 候选抽取 + 反思去重 + diff |
| 作用域 | user/agent/run | user/session/context type | user/agent | user/global/workspace | user/source_app/project/session |
| 审计 | SQLite history | memory_diff.json | 基础 CRUD | 基础 CRUD | memory_operation + evidence |
| 冲突处理 | hash dedup 为主 | LLM merge/delete | 手动更新 | workspace update | 首版 skip/create，后续 merge/conflict |

### 7.2 知识上传

| 维度 | mem0 | OpenViking | Khoj | AnythingLLM | 当前项目建议 |
|---|---|---|---|---|---|
| 主定位 | memory layer | context DB | second brain | chat with docs | personal context system |
| 文档解析 | 非重点 | parser registry | per-format entries | collector converters | parser registry + collector |
| 中间产物 | memory payload | AGFS tree | Entry rows | JSON documents | RawArtifact + ParsedDocument/Chunk |
| 切分 | memory facts | L0/L1/L2 tree | heading/page + token | recursive splitter | 结构优先 + token fallback |
| 向量关系 | memory id | URI index | Entry id | docId/vectorId | chunk_id/vector_id + doc_id |
| 同步删除 | memory delete | URI delete | hash diff | doc relation delete | checksum/hash diff + job |

### 7.3 检索

| 维度 | mem0 | OpenViking | Khoj | AnythingLLM | 当前项目建议 |
|---|---|---|---|---|---|
| 语义召回 | 是 | 是 | 是 | 是 | 是 |
| 关键词/BM25 | 是 | sparse/vector support | word filter | 视 provider | 必须 |
| 实体 boost | 是 | 可由 memory 分类支持 | 否 | 否 | 必须 |
| 时间推理 | README 强调 | session/history | date filters | lastUsedAt | date filters + temporal metadata |
| 层级检索 | 否 | 强 | 部分 heading | workspace/doc | L0/L1/L2 分阶段 |
| rerank | 可选 | thinking mode | cross-encoder | native reranker | 可选 |

## 8. 当前项目的推荐借鉴方案

### 8.1 总体架构

建议采用如下架构：

```text
                          ┌──────────────────────────┐
                          │        User / Agent       │
                          └────────────┬─────────────┘
                                       │
                  ┌────────────────────┴────────────────────┐
                  │                                         │
          Dream conversation ingest                 Knowledge upload
          Claude/Codex adapters                     file/link/raw adapters
                  │                                         │
                  ▼                                         ▼
        NormalizedTranscript                         RawArtifact
                  │                                         │
                  ▼                                         ▼
          SessionArchive                         Parser Registry
                  │                                         │
                  ▼                                         ▼
      Summary + Memory Candidate              ParsedDocument / Section
                  │                                         │
                  ▼                                         ▼
       Reflect/Dedup/Classify                    Chunk + L0/L1 jobs
                  │                                         │
                  └──────────────┬──────────────────────────┘
                                 ▼
                     Context Storage + Indexing
              SQL metadata + object files + vector + BM25
                                 │
                                 ▼
                       Unified Retrieval API
               memory/resource filters + rerank + evidence
```

### 8.2 核心数据模型建议

#### Source 与原始证据

所有自动写入都必须先落原始证据。

| 表/对象 | 关键字段 | 说明 |
|---|---|---|
| `source_app` | `id`, `name`, `type`, `enabled`, `config` | Claude Code、Codex、future adapter |
| `raw_artifact` | `id`, `source_app_id`, `kind`, `uri`, `checksum`, `metadata`, `created_at` | 原始 transcript、上传文件、链接抓取结果 |
| `ingest_job` | `id`, `artifact_id`, `status`, `stage`, `error`, `started_at`, `finished_at` | 解析/抽取/索引任务 |

#### Dream 会话

| 表/对象 | 关键字段 | 说明 |
|---|---|---|
| `conversation_session` | `id`, `source_app`, `external_session_id`, `project_path`, `repo`, `started_at`, `ended_at`, `status` | 外部会话到内部会话的稳定映射 |
| `conversation_turn` | `id`, `session_id`, `external_turn_id`, `role`, `content`, `parts_json`, `created_at`, `token_count`, `raw_ref` | 标准化 turn |
| `session_archive` | `id`, `session_id`, `archive_index`, `l0_abstract`, `l1_overview`, `raw_uri`, `committed_at` | commit 边界 |

#### Memory

| 表/对象 | 关键字段 | 说明 |
|---|---|---|
| `memory` | `id`, `scope`, `category`, `content`, `status`, `confidence`, `created_at`, `updated_at`, `last_used_at` | 一条长期记忆 |
| `memory_evidence` | `memory_id`, `session_id`, `turn_id`, `artifact_id`, `quote_ref`, `confidence` | 记忆来源证据 |
| `memory_entity` | `memory_id`, `entity_text`, `entity_type`, `normalized` | 实体链接 |
| `memory_operation` | `id`, `archive_id`, `op`, `memory_id`, `before`, `after`, `reasoning` | memory diff / rollback |

Memory scope 建议：

| scope | 含义 | 示例 |
|---|---|---|
| `global` | 跨项目长期适用 | 用户偏好中文回答、喜欢先看结论 |
| `workspace` | 某项目/目录内适用 | 当前项目使用 Next.js + Prisma |
| `session` | 只对某次会话有意义，可作为短期上下文 | 本轮尚未完成的 TODO |
| `agent` | 某 agent 的工具/行为经验 | Codex 在该 repo 中测试命令是 `pnpm test` |

Memory category 首版建议：

| category | 说明 | 更新策略 |
|---|---|---|
| `profile` | 用户身份、角色、长期背景 | 可合并 |
| `preference` | 表达、技术、工作流偏好 | 可合并 |
| `entity` | 人、项目、库、系统、文件等实体事实 | 可追加/合并 |
| `event` | 决策、里程碑、发生过的事 | 追加，默认不覆盖 |
| `procedure` | 可复用工作流、命令、项目惯例 | 可合并 |
| `lesson` | 从问题解决中总结出的经验 | 可合并 |

#### Resource / Knowledge

| 表/对象 | 关键字段 | 说明 |
|---|---|---|
| `resource` | `id`, `workspace_id`, `title`, `source_uri`, `mime`, `checksum`, `status`, `metadata` | 上传文档或链接 |
| `resource_node` | `id`, `resource_id`, `parent_id`, `level`, `title`, `path`, `l0_abstract`, `l1_overview` | 文档结构树 |
| `chunk` | `id`, `resource_id`, `node_id`, `text`, `compiled_text`, `page`, `line_start`, `line_end`, `token_count`, `hash` | 检索最小单元 |
| `vector_index_item` | `chunk_id` 或 `memory_id`, `vector_id`, `index_name`, `embedding_model` | 支持重建和删除 |

### 8.3 Dream 入口设计

建议定义通用 adapter：

```python
class TranscriptAdapter:
    source_app: str

    def detect(self) -> bool:
        ...

    def list_sessions(self, cursor: dict) -> list[ExternalSession]:
        ...

    def read_turns(self, session: ExternalSession, cursor: dict) -> list[RawTurn]:
        ...

    def normalize_turn(self, raw: RawTurn) -> ConversationTurn:
        ...
```

首版适配：

1. `ClaudeCodeTranscriptAdapter`
2. `CodexTranscriptAdapter`

预留：

1. Cursor / Windsurf / OpenCode
2. ChatGPT export
3. 自定义 JSONL/Markdown transcript
4. MCP/hook 实时写入

Dream pipeline：

```text
scan adapters
  -> detect new/changed sessions
  -> normalize turns
  -> save raw transcript + turns
  -> if session idle/closed/manual:
       create session_archive
       generate L1 session summary
       extract candidate memories
       search similar memories
       reflect/dedup/classify
       write memory + evidence + operation diff
       index memory
```

记忆抽取建议组合：

1. **Observer**：从会话里提取最多 N 条 candidate，带 category、confidence、evidence turn id、reasoning。
2. **Retriever**：按 candidate 搜索已有 memory，取相似项、同实体项、同 scope 项。
3. **Reflector**：判断 `skip/create/update/conflict`，并分类 `global/workspace/session/agent`。
4. **Writer**：写 memory、memory_evidence、memory_operation。

首版可限制：

1. 每个 session archive 最多提取 5-10 条 memory。
2. 低 confidence 默认不自动写入，只进 review queue。
3. assistant-only 内容默认不写用户 memory；但可写 `procedure/lesson/tool` 类 agent memory。
4. 对敏感类别（身份、健康、财务、密钥、隐私）默认进入 pending review。

### 8.4 知识上传入口设计

知识上传 pipeline：

```text
upload file/link/raw text
  -> save RawArtifact
  -> MIME detect + parser selection
  -> parse to ParsedDocument tree
  -> structural chunking
  -> hash diff / dedup
  -> write Resource/Node/Chunk
  -> async L0/L1 generation
  -> embedding + BM25 index
  -> status ready
```

Parser registry 建议：

| 类型 | 首版 parser | 后续增强 |
|---|---|---|
| Markdown / MDX | heading tree | frontmatter、wiki links |
| TXT / unknown text | recursive split | encoding detect |
| PDF | PyMuPDF/pdfplumber | OCR、table extraction |
| DOCX / PPTX / XLSX | office parser / python libs | 表格结构、图片 OCR |
| HTML / URL | readability + markdown | boilerplate removal |
| Code repo | gitignore-aware walker + AST skeleton | symbol graph |
| Image | OCR/VLM caption | layout detection |
| Audio/Video | transcription | segment timestamps |

切分策略：

1. 结构优先：heading、page、slide、sheet、section、code symbol。
2. 超长再 token fallback：500-1200 tokens，按文档类型配置 overlap。
3. `compiled_text` 前缀包含文件名、章节路径、页码/行号，提升 embedding 质量。
4. 每个 chunk 保留精确 source pointer：file path、page、line、URL fragment、timestamp。

索引策略：

1. dense embedding index：语义召回。
2. BM25/sparse index：关键词、人名、代码符号、错误信息。
3. metadata filter：source_app、workspace、file_type、date、tags、status。
4. entity index：memory 和 resource chunk 都可抽实体。
5. rerank：查询复杂或候选多时启用。

### 8.5 检索服务设计

统一 retrieval API：

```text
retrieve(query, target_types=[memory, resource], scope, filters, mode)
  -> query normalize
  -> intent/type planning (optional)
  -> dense search
  -> BM25 search
  -> entity/time/source boost
  -> merge + dedup
  -> optional rerank
  -> progressive load L0/L1/L2
  -> return contexts with evidence
```

结果对象建议：

| 字段 | 说明 |
|---|---|
| `id` | memory_id / chunk_id / node_id |
| `type` | memory/resource/session/skill |
| `scope` | global/workspace/session/agent |
| `score` | 融合分 |
| `score_details` | semantic/BM25/entity/recency/rerank |
| `content` | 注入模型的文本，优先 L0/L1 |
| `source` | 文件、会话、turn、URL |
| `evidence` | 可点击或可读取的证据引用 |
| `load_more_uri` | 需要 L2 时读取 |

## 9. 当前项目明确借鉴清单

### 必须借鉴

1. mem0：memory 以事实为单位，而不是保存完整聊天摘要。
2. mem0：混合检索，尤其 BM25 和实体 boost。
3. mem0/OpenMemory：memory 状态、来源 app、访问日志。
4. OpenViking：Resource/Memory/Skill 类型抽象。
5. OpenViking：L0/L1/L2 渐进上下文。
6. OpenViking：session commit + memory_diff。
7. OpenViking：Codex/Claude Code 生命周期经验，Stop capture、PreCompact/idle commit。
8. Khoj：文档 Entry 保留 raw/compiled/heading/file/uri。
9. Khoj：hash 增量索引、文件/日期/词过滤。
10. AnythingLLM：collector/server 分层和 document JSON 中间产物。
11. AnythingLLM：docId -> vectorId 映射和 vector-cache。
12. AnythingLLM：GLOBAL/WORKSPACE memory 和 Observer/Reflector。

### 谨慎借鉴

1. mem0 ADD-only：首版适合，但要保留 conflict/update 机制。
2. OpenViking 虚拟文件系统：理念好，MVP 可用 SQL + object storage 简化。
3. Khoj 小 chunk：适合短笔记，不适合所有文档。
4. AnythingLLM memory 硬上限：可以作为 prompt 注入上限，不应作为存储上限。

### 不建议借鉴

1. 只把内容塞进向量库，没有原文、证据、删除映射。
2. 自动抽取后直接覆盖用户 memory。
3. 没有 scope 的全局记忆。
4. 没有用户可见、可删、可停用的 memory UI/API。
5. 在上传请求同步完成所有解析、摘要、embedding。

## 10. 推荐 MVP 阶段

### Phase 1：基础数据层与 Dream 扫描

目标：能读取 Claude Code/Codex 记录，归档为标准 session。

范围：

1. 建立 `source_app`、`conversation_session`、`conversation_turn`、`session_archive`。
2. 实现 Claude Code / Codex adapter 的本地日志扫描和增量 cursor。
3. 保存原始 transcript artifact。
4. 支持手动触发 archive/commit。

验收：

1. 能列出会话。
2. 能查看标准化 turns。
3. 同一外部会话重复扫描不会重复写入。

### Phase 2：Memory 抽取与治理

目标：Dream 能从 session archive 生成可审计 memory。

范围：

1. session L1 summary。
2. Observer candidate extraction。
3. 相似 memory 检索 + Reflector 去重分类。
4. 写 `memory`、`memory_evidence`、`memory_operation`。
5. memory status：active/pending/archived/deleted。

验收：

1. 每条 memory 能追溯到 session/turn。
2. 重复会话不会产生大量重复 memory。
3. 用户能删除/停用 memory。

### Phase 3：知识上传与文档索引

目标：能上传常见文档并检索。

范围：

1. RawArtifact + Resource/Node/Chunk。
2. Parser registry：txt/md/pdf/docx/html。
3. Chunk hash diff。
4. dense embedding + BM25。
5. source pointer：file/page/line/url。

验收：

1. 上传文档后可看到解析状态。
2. 检索结果带来源。
3. 删除文档能删除相关 vectors。

### Phase 4：统一检索 API

目标：同时检索 memory 和 resource。

范围：

1. semantic + BM25 + metadata filters。
2. memory entity boost。
3. L0/L1/L2 progressive load。
4. score_details。

验收：

1. 能按 workspace/global 查询。
2. 能回答“我偏好什么”“某文档里怎么说”的混合问题。
3. 检索结果可解释。

### Phase 5：自动化与插件化

目标：接入更实时的 Dream 和外部工具。

范围：

1. Claude/Codex hook 插件或 watcher。
2. idle/compact 自动 commit。
3. review queue。
4. 新 adapter SDK。

验收：

1. 正常使用 Claude/Codex 后无需手动导入。
2. 退出/崩溃/compact 有兜底提交。
3. 用户可按 source_app 暂停写入。

## 11. 风险与开放问题

| 风险 | 说明 | 建议 |
|---|---|---|
| 自动记忆污染 | LLM 把临时信息、误解、助手输出写入长期记忆 | confidence、evidence、pending review、敏感类别过滤 |
| 重复和矛盾 | ADD-only 会积累近似重复或旧事实 | hash + embedding dedup + entity conflict detection |
| 隐私与安全 | 对话里可能含密钥、路径、客户信息 | secret scanner、source_app opt-out、加密存储、删除可追踪 |
| 文档任意格式过宽 | OCR/表格/图片/视频解析成本高 | parser registry 分层，首版常见格式，失败可重试 |
| 检索不可解释 | 用户不信任 memory 来源 | 所有结果返回 evidence/source |
| 过早复杂化 | 完整 OpenViking 式文件系统实现成本高 | 先用 SQL schema + URI 约定，后续演进 |
| Hook 生命周期不可靠 | Codex/Claude 退出不一定有 hook | 本地日志扫描作为真源，hook 只做增量捕获 |

开放问题：

1. 当前项目最终运行形态是本地单机、Web 服务，还是多用户服务？
2. 首选存储是 SQLite/LanceDB，还是 Postgres/pgvector？
3. 是否需要端到端加密或至少本地加密？
4. Dream 是否只读本机日志，还是要接浏览器/云端导出？
5. 文档上传是否包含代码仓库、音视频和图片，还是首版只做文本类文档？

## 12. 最终建议

当前项目不要直接复制任何单个项目，而是采用组合方案：

1. **底层上下文模型参考 OpenViking**：Resource/Memory/Skill + L0/L1/L2 + session commit。
2. **memory 抽取参考 mem0 + AnythingLLM**：mem0 的事实化与混合检索，AnythingLLM 的 Observer/Reflector 和 global/workspace scope。
3. **文档入口参考 Khoj + AnythingLLM**：Khoj 的结构化 Entry 与增量 hash，AnythingLLM 的 collector/server 分层、document JSON、docId/vectorId。
4. **治理参考 OpenMemory + OpenViking**：状态、ACL/来源、访问日志、memory diff、人工删除/回滚。

推荐首版实现最小闭环：

```text
Claude/Codex transcript scan
  -> session archive
  -> summary
  -> evidence-backed memory
  -> hybrid retrieval

Document upload
  -> parsed chunks with source pointer
  -> embedding + BM25
  -> retrieval with citations
```

只要这个闭环做稳，后续再加 hooks、更多 parser、层级检索、UI review、自动同步都会自然很多。
