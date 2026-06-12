import { useEffect, useMemo, useState } from "react";
import {
  BookOpen,
  Brain,
  Check,
  Database,
  FileText,
  GitBranch,
  Link2,
  ListChecks,
  LoaderCircle,
  Moon,
  Network,
  Play,
  RefreshCw,
  RotateCcw,
  Search,
  Trash2,
  Upload,
  X,
} from "lucide-react";

const tabs = [
  { id: "retrieve", label: "Retrieve", icon: Search },
  { id: "memories", label: "Memories", icon: Brain },
  { id: "resources", label: "Knowledge", icon: BookOpen },
  { id: "dream", label: "Dream", icon: Moon },
  { id: "jobs", label: "Jobs", icon: ListChecks },
  { id: "graph", label: "Graph", icon: Network },
];

async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json();
}

function jsonBody(payload) {
  return {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  };
}

function countText(count, singular, plural = `${singular}s`) {
  return `${count} ${count === 1 ? singular : plural}`;
}

function App() {
  const [activeTab, setActiveTab] = useState("retrieve");
  const [health, setHealth] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const [retrieveQuery, setRetrieveQuery] = useState("");
  const [retrieveType, setRetrieveType] = useState("");
  const [retrieveResults, setRetrieveResults] = useState([]);

  const [memoryContent, setMemoryContent] = useState("");
  const [memoryScope, setMemoryScope] = useState("global");
  const [memoryCategory, setMemoryCategory] = useState("preference");
  const [memories, setMemories] = useState([]);
  const [review, setReview] = useState([]);
  const [relationsById, setRelationsById] = useState({});

  const [textTitle, setTextTitle] = useState("Untitled Text");
  const [textBody, setTextBody] = useState("");
  const [file, setFile] = useState(null);
  const [urlInput, setUrlInput] = useState("");
  const [resources, setResources] = useState([]);

  const [dreamPaths, setDreamPaths] = useState("");
  const [sessions, setSessions] = useState([]);

  const [jobs, setJobs] = useState([]);
  const [graphQuery, setGraphQuery] = useState("");
  const [graphStatus, setGraphStatus] = useState("");
  const [graphResults, setGraphResults] = useState([]);

  const activeTitle = useMemo(
    () => tabs.find((tab) => tab.id === activeTab)?.label ?? "BHD Memory",
    [activeTab],
  );
  const openJobs = jobs.filter((item) => !["done", "failed"].includes(item.status)).length;

  async function runAction(action) {
    setLoading(true);
    setError("");
    try {
      await action();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  async function refreshHealth() {
    const data = await api("/health");
    setHealth(data);
  }

  async function loadMemories() {
    setMemories(await api("/api/memories?status=active"));
  }

  async function loadReview() {
    setReview(await api("/api/memories/review"));
  }

  async function loadResources() {
    setResources(await api("/api/resources?status=ready"));
  }

  async function loadSessions() {
    setSessions(await api("/api/dream/sessions"));
  }

  async function loadJobs() {
    setJobs(await api("/api/jobs"));
  }

  async function refreshAll() {
    await Promise.all([
      refreshHealth(),
      loadMemories(),
      loadReview(),
      loadResources(),
      loadSessions(),
      loadJobs(),
    ]);
  }

  useEffect(() => {
    runAction(refreshAll);
  }, []);

  async function runRetrieve() {
    const query = retrieveQuery.trim();
    if (!query) return;
    const data = await api(
      "/api/retrieve",
      jsonBody({
        query,
        target_types: retrieveType ? [retrieveType] : null,
        limit: 10,
      }),
    );
    setRetrieveResults(data);
  }

  async function createMemory() {
    if (!memoryContent.trim()) return;
    await api(
      "/api/memories",
      jsonBody({
        content: memoryContent,
        scope: memoryScope,
        category: memoryCategory,
      }),
    );
    setMemoryContent("");
    await Promise.all([loadMemories(), loadReview()]);
  }

  async function deleteMemory(id) {
    await api(`/api/memories/${id}`, { method: "DELETE" });
    await loadMemories();
  }

  async function approveMemory(id) {
    await api(`/api/memories/${id}/approve`, { method: "POST" });
    await Promise.all([loadReview(), loadMemories()]);
  }

  async function rejectMemory(id) {
    await api(`/api/memories/${id}/reject`, { method: "POST" });
    await loadReview();
  }

  async function loadRelations(id) {
    const data = await api(`/api/memories/${id}/relations`);
    setRelationsById((current) => ({ ...current, [id]: data }));
  }

  async function uploadText() {
    if (!textBody.trim()) return;
    await api("/api/resources/text", jsonBody({ title: textTitle, text: textBody }));
    setTextBody("");
    await loadResources();
  }

  async function uploadFile() {
    if (!file) return;
    const body = new FormData();
    body.append("file", file);
    await api("/api/resources/upload", { method: "POST", body });
    setFile(null);
    document.getElementById("fileInput").value = "";
    await loadResources();
  }

  async function uploadUrl() {
    const url = urlInput.trim();
    if (!url) return;
    await api("/api/resources/link", jsonBody({ url }));
    setUrlInput("");
    await loadResources();
  }

  async function deleteResource(id) {
    await api(`/api/resources/${id}`, { method: "DELETE" });
    await loadResources();
  }

  async function scanDream(autoCommit) {
    const paths = dreamPaths
      .split("\n")
      .map((item) => item.trim())
      .filter(Boolean);
    await api("/api/dream/scan", jsonBody({ paths: paths.length ? paths : null, auto_commit: autoCommit }));
    await Promise.all([loadSessions(), loadMemories(), loadReview()]);
  }

  async function commitSession(id) {
    await api(`/api/dream/sessions/${id}/commit`, { method: "POST" });
    await Promise.all([loadSessions(), loadMemories(), loadReview()]);
  }

  async function runJobs() {
    await api("/api/jobs/run-until-idle", { method: "POST" });
    await Promise.all([loadJobs(), loadResources(), loadMemories(), loadReview()]);
  }

  async function rebuildIndex(clear) {
    await api("/api/index/rebuild", jsonBody({ clear }));
    await loadJobs();
  }

  async function syncGraph(external) {
    const data = await api("/api/graph/sync", jsonBody({ external }));
    setGraphStatus(JSON.stringify(data));
    await loadEpisodes();
  }

  async function loadEpisodes() {
    setGraphResults(await api("/api/graph/episodes"));
  }

  async function searchGraph() {
    const query = graphQuery.trim();
    if (!query) return;
    setGraphResults(await api(`/api/graph/entities/search?query=${encodeURIComponent(query)}`));
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">B</div>
          <div className="brand-copy">
            <strong>BHD Memory</strong>
            <span>Local memory workspace</span>
          </div>
        </div>

        <div className="sidebar-panel">
          <div className="nav-label">Workspace</div>
          <nav className="nav-list" aria-label="Main navigation">
            {tabs.map((tab) => {
              const Icon = tab.icon;
              return (
                <button
                  key={tab.id}
                  className={`nav-item ${activeTab === tab.id ? "active" : ""}`}
                  onClick={() => setActiveTab(tab.id)}
                >
                  <span className="nav-icon"><Icon size={16} strokeWidth={2.2} /></span>
                  <span>{tab.label}</span>
                </button>
              );
            })}
          </nav>

          <div className="sidebar-footer">
            <HealthPill health={health} />
          </div>
        </div>
      </aside>

      <main className="workspace">
        <div className="workspace-frame">
          <header className="topbar">
            <div>
              <p className="eyebrow">Personal Memory + Knowledge Base</p>
              <h1>{activeTitle}</h1>
            </div>
            <div className="top-actions">
              <div className="collection-pill">
                <Database size={15} />
                <span>{health?.qdrant?.collection ?? "pending"}</span>
              </div>
              <Button variant="secondary" icon={RefreshCw} onClick={() => runAction(refreshAll)}>
                Refresh
              </Button>
            </div>
          </header>

          {error ? (
            <div className="error-banner">
              <X size={16} />
              <span>{error}</span>
            </div>
          ) : null}

          {loading ? (
            <div className="loading-bar">
              <LoaderCircle size={15} className="spin" />
              <span>Working</span>
            </div>
          ) : null}

          <div className="views">
            {activeTab === "retrieve" ? (
              <RetrieveView
                retrieveQuery={retrieveQuery}
                setRetrieveQuery={setRetrieveQuery}
                retrieveType={retrieveType}
                setRetrieveType={setRetrieveType}
                retrieveResults={retrieveResults}
                runRetrieve={() => runAction(runRetrieve)}
                counts={{
                  memories: memories.length,
                  resources: resources.length,
                  jobs: openJobs,
                  review: review.length,
                }}
              />
            ) : null}

            {activeTab === "memories" ? (
              <MemoriesView
                memoryContent={memoryContent}
                setMemoryContent={setMemoryContent}
                memoryScope={memoryScope}
                setMemoryScope={setMemoryScope}
                memoryCategory={memoryCategory}
                setMemoryCategory={setMemoryCategory}
                memories={memories}
                review={review}
                relationsById={relationsById}
                createMemory={() => runAction(createMemory)}
                loadMemories={() => runAction(loadMemories)}
                loadReview={() => runAction(loadReview)}
                deleteMemory={(id) => runAction(() => deleteMemory(id))}
                approveMemory={(id) => runAction(() => approveMemory(id))}
                rejectMemory={(id) => runAction(() => rejectMemory(id))}
                loadRelations={(id) => runAction(() => loadRelations(id))}
              />
            ) : null}

            {activeTab === "resources" ? (
              <ResourcesView
                textTitle={textTitle}
                setTextTitle={setTextTitle}
                textBody={textBody}
                setTextBody={setTextBody}
                setFile={setFile}
                urlInput={urlInput}
                setUrlInput={setUrlInput}
                resources={resources}
                uploadText={() => runAction(uploadText)}
                uploadFile={() => runAction(uploadFile)}
                uploadUrl={() => runAction(uploadUrl)}
                loadResources={() => runAction(loadResources)}
                deleteResource={(id) => runAction(() => deleteResource(id))}
              />
            ) : null}

            {activeTab === "dream" ? (
              <DreamView
                dreamPaths={dreamPaths}
                setDreamPaths={setDreamPaths}
                sessions={sessions}
                scanDream={(autoCommit) => runAction(() => scanDream(autoCommit))}
                loadSessions={() => runAction(loadSessions)}
                commitSession={(id) => runAction(() => commitSession(id))}
              />
            ) : null}

            {activeTab === "jobs" ? (
              <JobsView
                jobs={jobs}
                loadJobs={() => runAction(loadJobs)}
                runJobs={() => runAction(runJobs)}
                rebuildIndex={(clear) => runAction(() => rebuildIndex(clear))}
              />
            ) : null}

            {activeTab === "graph" ? (
              <GraphView
                graphQuery={graphQuery}
                setGraphQuery={setGraphQuery}
                graphStatus={graphStatus}
                graphResults={graphResults}
                syncGraph={(external) => runAction(() => syncGraph(external))}
                loadEpisodes={() => runAction(loadEpisodes)}
                searchGraph={() => runAction(searchGraph)}
              />
            ) : null}
          </div>
        </div>
      </main>
    </div>
  );
}

function HealthPill({ health }) {
  const ok = health?.qdrant?.ok;
  return (
    <div className="health-stack">
      <div className="health-pill">
        <span className={`status-dot ${ok ? "ok" : health ? "bad" : ""}`} />
        <span>{ok ? "Qdrant connected" : health ? "Qdrant unavailable" : "checking"}</span>
      </div>
      <span className="health-url">{health?.qdrant?.url ?? "qdrant pending"}</span>
    </div>
  );
}

function Button({ children, icon: Icon, variant = "primary", className = "", ...props }) {
  return (
    <button className={`btn ${variant} ${className}`} {...props}>
      {Icon ? <Icon size={15} strokeWidth={2.2} /> : null}
      <span>{children}</span>
    </button>
  );
}

function SectionHead({ title, subtitle, actions }) {
  return (
    <div className="section-head">
      <div>
        <h2>{title}</h2>
        <p>{subtitle}</p>
      </div>
      {actions ? <div className="toolbar">{actions}</div> : null}
    </div>
  );
}

function Panel({ title, meta, children, className = "" }) {
  return (
    <div className={`panel ${className}`}>
      {title ? (
        <div className="panel-title">
          <h3>{title}</h3>
          {meta ? <span>{meta}</span> : null}
        </div>
      ) : null}
      {children}
    </div>
  );
}

function Empty({ children }) {
  return <div className="empty">{children}</div>;
}

function RetrieveView({
  retrieveQuery,
  setRetrieveQuery,
  retrieveType,
  setRetrieveType,
  retrieveResults,
  runRetrieve,
  counts,
}) {
  return (
    <section className="view active">
      <SectionHead
        title="Retrieve"
        subtitle="Search across approved memories and parsed knowledge chunks."
      />
      <div className="metric-row">
        <Metric value={counts.memories} label="active memories" />
        <Metric value={counts.resources} label="ready resources" />
        <Metric value={counts.jobs} label="open jobs" />
        <Metric value={counts.review} label="review queue" />
      </div>
      <Panel>
        <div className="searchbar">
          <input
            value={retrieveQuery}
            onChange={(event) => setRetrieveQuery(event.target.value)}
            onKeyDown={(event) => event.key === "Enter" && runRetrieve()}
            placeholder="Search memories and knowledge"
          />
          <select value={retrieveType} onChange={(event) => setRetrieveType(event.target.value)}>
            <option value="">All</option>
            <option value="memory">Memory</option>
            <option value="resource">Knowledge</option>
          </select>
          <Button icon={Search} onClick={runRetrieve}>Search</Button>
        </div>
        <div className="divider" />
        <div className="list">
          {retrieveResults.length ? retrieveResults.map((item, index) => (
            <ResultItem key={`${item.type}-${item.load_more_uri}-${index}`} item={item} />
          )) : <Empty>No search results</Empty>}
        </div>
      </Panel>
    </section>
  );
}

function Metric({ value, label }) {
  return (
    <div className="metric">
      <strong>{value}</strong>
      <span>{label}</span>
    </div>
  );
}

function ResultItem({ item }) {
  const source = item.source || {};
  return (
    <div className="item">
      <div className="item-row">
        <strong>{item.type} <span className="tag">{Number(item.score).toFixed(4)}</span></strong>
        <span className="meta">{source.title || source.kind || ""}</span>
      </div>
      <div className="content">{item.content}</div>
      {item.load_more_uri ? <div className="meta mono">{item.load_more_uri}</div> : null}
    </div>
  );
}

function MemoriesView(props) {
  return (
    <section className="view active">
      <SectionHead
        title="Memories"
        subtitle="Create, review, approve, and remove durable memory facts."
        actions={
          <>
            <Button variant="secondary" icon={RefreshCw} onClick={props.loadMemories}>Refresh</Button>
            <Button variant="secondary" icon={ListChecks} onClick={props.loadReview}>Review</Button>
          </>
        }
      />
      <div className="grid wide-left">
        <Panel title="New Memory" meta="truth store + Qdrant index" className="stack">
          <label>
            Content
            <textarea value={props.memoryContent} onChange={(event) => props.setMemoryContent(event.target.value)} />
          </label>
          <div className="toolbar">
            <select value={props.memoryScope} onChange={(event) => props.setMemoryScope(event.target.value)}>
              <option value="global">global</option>
              <option value="workspace">workspace</option>
              <option value="session">session</option>
              <option value="agent">agent</option>
            </select>
            <select value={props.memoryCategory} onChange={(event) => props.setMemoryCategory(event.target.value)}>
              <option value="preference">preference</option>
              <option value="profile">profile</option>
              <option value="entity">entity</option>
              <option value="event">event</option>
              <option value="procedure">procedure</option>
              <option value="lesson">lesson</option>
            </select>
            <Button icon={Check} onClick={props.createMemory}>Add</Button>
          </div>
        </Panel>
        <Panel title="Review Queue" meta={countText(props.review.length, "pending")}>
          <div className="list">
            {props.review.length ? props.review.map((item) => (
              <ReviewItem
                key={item.id}
                item={item}
                relations={props.relationsById[item.id] || []}
                onRelations={() => props.loadRelations(item.id)}
                onApprove={() => props.approveMemory(item.id)}
                onReject={() => props.rejectMemory(item.id)}
              />
            )) : <Empty>No pending memories</Empty>}
          </div>
        </Panel>
      </div>
      <Panel title="Active Memories" meta={countText(props.memories.length, "active")} className="spaced">
        <div className="list">
          {props.memories.length ? props.memories.map((item) => (
            <div className="item" key={item.id}>
              <div className="item-row">
                <strong>{item.category} / {item.scope}</strong>
                <Button variant="danger" icon={Trash2} onClick={() => props.deleteMemory(item.id)}>Delete</Button>
              </div>
              <div className="content">{item.content}</div>
              <div className="meta mono">{item.id}</div>
            </div>
          )) : <Empty>No active memories</Empty>}
        </div>
      </Panel>
    </section>
  );
}

function ReviewItem({ item, relations, onRelations, onApprove, onReject }) {
  return (
    <div className="item">
      <div className="item-row">
        <strong>Review · {item.category} / {item.scope}</strong>
        <span className="toolbar compact">
          <Button variant="secondary" icon={GitBranch} onClick={onRelations}>Relations</Button>
          <Button variant="secondary" icon={Check} onClick={onApprove}>Approve</Button>
          <Button variant="danger" icon={X} onClick={onReject}>Reject</Button>
        </span>
      </div>
      <div className="content">{item.content}</div>
      <div className="meta">{item.status} · <span className="mono">{item.id}</span></div>
      {relations.length ? (
        <div className="relations">
          {relations.map((relation) => (
            <div key={relation.id || `${relation.source_id}-${relation.target_id}`}>
              {relation.relation_type}: {relation.source_content} -&gt; {relation.target_content}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function ResourcesView(props) {
  return (
    <section className="view active">
      <SectionHead
        title="Knowledge"
        subtitle="Upload text, files, and links into the parsed resource index."
        actions={<Button variant="secondary" icon={RefreshCw} onClick={props.loadResources}>Refresh</Button>}
      />
      <div className="grid">
        <Panel title="Text Resource" meta="direct ingest" className="stack">
          <label>Text Title<input value={props.textTitle} onChange={(event) => props.setTextTitle(event.target.value)} /></label>
          <label>Text<textarea value={props.textBody} onChange={(event) => props.setTextBody(event.target.value)} /></label>
          <Button icon={FileText} onClick={props.uploadText}>Upload Text</Button>
        </Panel>
        <Panel title="File or URL" meta="parser pipeline" className="stack">
          <label>File<input id="fileInput" type="file" onChange={(event) => props.setFile(event.target.files?.[0] || null)} /></label>
          <Button icon={Upload} onClick={props.uploadFile}>Upload File</Button>
          <div className="divider" />
          <label>URL<input value={props.urlInput} onChange={(event) => props.setUrlInput(event.target.value)} placeholder="https://example.com/doc.html" /></label>
          <Button variant="secondary" icon={Link2} onClick={props.uploadUrl}>Fetch URL</Button>
        </Panel>
      </div>
      <Panel title="Resources" meta={countText(props.resources.length, "ready")} className="spaced">
        <div className="list">
          {props.resources.length ? props.resources.map((item) => (
            <div className="item" key={item.id}>
              <div className="item-row">
                <strong>{item.title}</strong>
                <Button variant="danger" icon={Trash2} onClick={() => props.deleteResource(item.id)}>Delete</Button>
              </div>
              <div className="meta">{item.mime} · {item.source_uri}</div>
            </div>
          )) : <Empty>No resources</Empty>}
        </div>
      </Panel>
    </section>
  );
}

function DreamView({ dreamPaths, setDreamPaths, sessions, scanDream, loadSessions, commitSession }) {
  return (
    <section className="view active">
      <SectionHead
        title="Dream"
        subtitle="Scan Claude Code, Codex, or JSONL transcripts and commit summaries into memory."
        actions={<Button variant="secondary" icon={RefreshCw} onClick={loadSessions}>Refresh</Button>}
      />
      <div className="grid wide-left">
        <Panel title="Transcript Paths" meta="one path per line" className="stack">
          <label>
            Paths
            <textarea value={dreamPaths} onChange={(event) => setDreamPaths(event.target.value)} placeholder="/path/to/session.jsonl" />
          </label>
          <div className="toolbar">
            <Button icon={Search} onClick={() => scanDream(false)}>Scan</Button>
            <Button variant="secondary" icon={Check} onClick={() => scanDream(true)}>Scan + Commit</Button>
          </div>
        </Panel>
        <Panel title="Sessions" meta={countText(sessions.length, "session")}>
          <div className="list">
            {sessions.length ? sessions.map((item) => (
              <div className="item" key={item.id}>
                <div className="item-row">
                  <strong>{item.source_name || item.source_app_id} · {item.status}</strong>
                  <Button variant="secondary" icon={Check} onClick={() => commitSession(item.id)}>Commit</Button>
                </div>
                <div className="meta">{item.external_session_id} · turns {item.turn_count || 0}</div>
              </div>
            )) : <Empty>No sessions</Empty>}
          </div>
        </Panel>
      </div>
    </section>
  );
}

function JobsView({ jobs, loadJobs, runJobs, rebuildIndex }) {
  return (
    <section className="view active">
      <SectionHead
        title="Jobs"
        subtitle="Inspect queued work, run workers, and rebuild Qdrant indexes."
        actions={
          <>
            <Button variant="secondary" icon={RefreshCw} onClick={loadJobs}>Refresh</Button>
            <Button icon={Play} onClick={runJobs}>Run Until Idle</Button>
          </>
        }
      />
      <Panel>
        <div className="toolbar panel-actions">
          <Button variant="secondary" icon={RotateCcw} onClick={() => rebuildIndex(false)}>Rebuild Index</Button>
          <Button variant="danger" icon={Trash2} onClick={() => rebuildIndex(true)}>Clear + Rebuild</Button>
        </div>
        <div className="list">
          {jobs.length ? jobs.map((item) => (
            <div className="item" key={item.id}>
              <div className="item-row">
                <strong>{item.pipeline} · {item.status}</strong>
                <span className="tag">{item.attempts} attempts</span>
              </div>
              <div className="meta">{item.stage} · <span className="mono">{item.id}</span></div>
              {item.error ? <div className="meta danger-text">{item.error}</div> : null}
            </div>
          )) : <Empty>No queued jobs</Empty>}
        </div>
      </Panel>
    </section>
  );
}

function GraphView(props) {
  return (
    <section className="view active">
      <SectionHead
        title="Graph"
        subtitle="Sync local graph episodes and search extracted entities."
        actions={
          <>
            <Button icon={Network} onClick={() => props.syncGraph(false)}>Sync Local Graph</Button>
            <Button variant="secondary" icon={GitBranch} onClick={() => props.syncGraph(true)}>Sync External</Button>
            <Button variant="secondary" icon={RefreshCw} onClick={props.loadEpisodes}>Episodes</Button>
          </>
        }
      />
      <div className="grid wide-right">
        <Panel title="Entity Search" meta="graph index" className="stack">
          <label>
            Query
            <input
              value={props.graphQuery}
              onChange={(event) => props.setGraphQuery(event.target.value)}
              onKeyDown={(event) => event.key === "Enter" && props.searchGraph()}
              placeholder="Graphiti, Qdrant, project name"
            />
          </label>
          <Button variant="secondary" icon={Search} onClick={props.searchGraph}>Search Entities</Button>
          {props.graphStatus ? <div className="meta mono">{props.graphStatus}</div> : null}
        </Panel>
        <Panel title="Graph Results" meta="episodes and entities">
          <div className="list">
            {props.graphResults.length ? props.graphResults.map((item) => (
              <div className="item" key={item.id}>
                <div className="item-row">
                  <strong>{item.entity_text || `${item.target_type} · ${item.name}`}</strong>
                  <span className="tag">{item.entity_type || item.external_status}</span>
                </div>
                {item.body ? <div className="content">{item.body.slice(0, 500)}</div> : null}
                <div className="meta">
                  {item.episode_name || item.group_id} · {item.target_type}:{item.target_id || item.id}
                </div>
              </div>
            )) : <Empty>No graph results</Empty>}
          </div>
        </Panel>
      </div>
    </section>
  );
}

export default App;
