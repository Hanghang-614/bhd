INDEX_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>BHD Memory</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f7f8fa;
      --panel: #ffffff;
      --line: #d8dde3;
      --text: #1f2933;
      --muted: #627084;
      --accent: #2f7d69;
      --accent-strong: #245f51;
      --danger: #a43d3d;
      --code: #eef2f5;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font: 14px/1.45 ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--text);
      background: var(--bg);
    }
    header {
      height: 56px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 20px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
      position: sticky;
      top: 0;
      z-index: 2;
    }
    h1 {
      margin: 0;
      font-size: 18px;
      font-weight: 700;
      letter-spacing: 0;
    }
    main {
      display: grid;
      grid-template-columns: 220px minmax(0, 1fr);
      min-height: calc(100vh - 56px);
    }
    nav {
      border-right: 1px solid var(--line);
      background: #fbfcfd;
      padding: 14px;
    }
    nav button {
      width: 100%;
      height: 36px;
      margin-bottom: 6px;
      border: 1px solid transparent;
      border-radius: 6px;
      background: transparent;
      color: var(--text);
      text-align: left;
      padding: 0 10px;
      cursor: pointer;
    }
    nav button.active {
      background: #e7f1ee;
      border-color: #bfd9d1;
      color: var(--accent-strong);
      font-weight: 650;
    }
    section {
      display: none;
      padding: 18px 22px 32px;
      max-width: 1180px;
      width: 100%;
    }
    section.active { display: block; }
    h2 {
      font-size: 16px;
      margin: 0 0 14px;
      letter-spacing: 0;
    }
    .toolbar {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-bottom: 14px;
      align-items: center;
    }
    input, textarea, select {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px 10px;
      background: #fff;
      color: var(--text);
      font: inherit;
    }
    textarea {
      min-height: 98px;
      resize: vertical;
    }
    label {
      display: grid;
      gap: 5px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 650;
    }
    button.action {
      min-height: 36px;
      border: 1px solid var(--accent);
      border-radius: 6px;
      padding: 0 12px;
      background: var(--accent);
      color: #fff;
      font-weight: 650;
      cursor: pointer;
    }
    button.secondary {
      min-height: 36px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 0 12px;
      background: #fff;
      color: var(--text);
      cursor: pointer;
    }
    button.danger {
      border-color: var(--danger);
      color: var(--danger);
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
    }
    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
    }
    .list {
      display: grid;
      gap: 8px;
    }
    .item {
      background: #fff;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 11px;
    }
    .item-row {
      display: flex;
      align-items: start;
      justify-content: space-between;
      gap: 10px;
    }
    .meta {
      color: var(--muted);
      font-size: 12px;
      margin-top: 4px;
      word-break: break-word;
    }
    .content {
      white-space: pre-wrap;
      word-break: break-word;
    }
    .mono {
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      background: var(--code);
      border-radius: 4px;
      padding: 2px 4px;
    }
    .status {
      color: var(--muted);
      font-size: 12px;
    }
    @media (max-width: 760px) {
      main { grid-template-columns: 1fr; }
      nav {
        display: flex;
        overflow-x: auto;
        border-right: 0;
        border-bottom: 1px solid var(--line);
      }
      nav button {
        width: auto;
        white-space: nowrap;
        margin-bottom: 0;
      }
      .grid { grid-template-columns: 1fr; }
      header { padding: 0 14px; }
      section { padding: 14px; }
    }
  </style>
</head>
<body>
  <header>
    <h1>BHD Memory</h1>
    <div id="health" class="status">checking</div>
  </header>
  <main>
    <nav>
      <button data-tab="retrieve" class="active">Retrieve</button>
      <button data-tab="memories">Memories</button>
      <button data-tab="resources">Knowledge</button>
      <button data-tab="dream">Dream</button>
      <button data-tab="jobs">Jobs</button>
      <button data-tab="graph">Graph</button>
    </nav>

    <section id="retrieve" class="active">
      <h2>Retrieve</h2>
      <div class="panel">
        <div class="toolbar">
          <input id="retrieveQuery" placeholder="Search memories and knowledge" />
          <select id="retrieveType" style="max-width: 180px">
            <option value="">All</option>
            <option value="memory">Memory</option>
            <option value="resource">Knowledge</option>
          </select>
          <button class="action" onclick="runRetrieve()">Search</button>
        </div>
        <div id="retrieveResults" class="list"></div>
      </div>
    </section>

    <section id="memories">
      <h2>Memories</h2>
      <div class="grid">
        <div class="panel">
          <label>Content<textarea id="memoryContent"></textarea></label>
          <div class="toolbar">
            <select id="memoryScope">
              <option value="global">global</option>
              <option value="workspace">workspace</option>
              <option value="session">session</option>
              <option value="agent">agent</option>
            </select>
            <select id="memoryCategory">
              <option value="preference">preference</option>
              <option value="profile">profile</option>
              <option value="entity">entity</option>
              <option value="event">event</option>
              <option value="procedure">procedure</option>
              <option value="lesson">lesson</option>
            </select>
            <button class="action" onclick="createMemory()">Add</button>
          </div>
        </div>
        <div class="panel">
          <div class="toolbar">
            <button class="secondary" onclick="loadMemories()">Refresh</button>
            <button class="secondary" onclick="loadReview()">Review</button>
          </div>
          <div id="memoryList" class="list"></div>
          <div id="reviewList" class="list" style="margin-top:10px"></div>
        </div>
      </div>
    </section>

    <section id="resources">
      <h2>Knowledge</h2>
      <div class="grid">
        <div class="panel">
          <label>Text Title<input id="textTitle" value="Untitled Text" /></label>
          <label>Text<textarea id="textBody"></textarea></label>
          <button class="action" onclick="uploadText()">Upload Text</button>
        </div>
        <div class="panel">
          <label>File<input id="fileInput" type="file" /></label>
          <button class="action" onclick="uploadFile()">Upload File</button>
          <hr />
          <label>URL<input id="urlInput" placeholder="https://example.com/doc.html" /></label>
          <button class="secondary" onclick="uploadUrl()">Fetch URL</button>
        </div>
      </div>
      <div class="panel" style="margin-top:14px">
        <div class="toolbar">
          <button class="secondary" onclick="loadResources()">Refresh</button>
        </div>
        <div id="resourceList" class="list"></div>
      </div>
    </section>

    <section id="dream">
      <h2>Dream</h2>
      <div class="grid">
        <div class="panel">
          <label>Transcript Paths<textarea id="dreamPaths" placeholder="/path/to/session.jsonl"></textarea></label>
          <div class="toolbar">
            <button class="action" onclick="scanDream(false)">Scan</button>
            <button class="secondary" onclick="scanDream(true)">Scan + Commit</button>
          </div>
        </div>
        <div class="panel">
          <div class="toolbar">
            <button class="secondary" onclick="loadSessions()">Refresh</button>
          </div>
          <div id="sessionList" class="list"></div>
        </div>
      </div>
    </section>

    <section id="jobs">
      <h2>Jobs</h2>
      <div class="panel">
        <div class="toolbar">
          <button class="secondary" onclick="loadJobs()">Refresh</button>
          <button class="action" onclick="runJobs()">Run Until Idle</button>
          <button class="secondary" onclick="rebuildIndex(false)">Rebuild Index</button>
          <button class="secondary danger" onclick="rebuildIndex(true)">Clear + Rebuild</button>
        </div>
        <div id="jobList" class="list"></div>
      </div>
    </section>

    <section id="graph">
      <h2>Graph</h2>
      <div class="grid">
        <div class="panel">
          <div class="toolbar">
            <button class="action" onclick="syncGraph(false)">Sync Local Graph</button>
            <button class="secondary" onclick="syncGraph(true)">Sync External</button>
            <button class="secondary" onclick="loadEpisodes()">Episodes</button>
          </div>
          <label>Entity Search<input id="graphQuery" placeholder="Graphiti, Qdrant, project name" /></label>
          <button class="secondary" onclick="searchGraph()">Search Entities</button>
        </div>
        <div class="panel">
          <div id="graphStatus" class="meta"></div>
          <div id="graphList" class="list"></div>
        </div>
      </div>
    </section>
  </main>
  <script>
    const $ = (id) => document.getElementById(id);
    const api = async (path, options = {}) => {
      const res = await fetch(path, options);
      if (!res.ok) throw new Error(await res.text());
      return res.json();
    };
    const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[char]));

    document.querySelectorAll("nav button").forEach((button) => {
      button.addEventListener("click", () => {
        document.querySelectorAll("nav button, section").forEach((el) => el.classList.remove("active"));
        button.classList.add("active");
        $(button.dataset.tab).classList.add("active");
      });
    });

    async function refreshHealth() {
      try {
        const data = await api("/health");
        $("health").textContent = data.qdrant.ok ? "Qdrant connected" : "Qdrant unavailable";
      } catch {
        $("health").textContent = "service unavailable";
      }
    }

    async function runRetrieve() {
      const query = $("retrieveQuery").value.trim();
      if (!query) return;
      const type = $("retrieveType").value;
      const data = await api("/api/retrieve", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ query, target_types: type ? [type] : null, limit: 10 })
      });
      $("retrieveResults").innerHTML = data.map(renderContext).join("");
    }

    function renderContext(item) {
      const source = item.source || {};
      return `<div class="item">
        <div class="item-row">
          <strong>${esc(item.type)} <span class="mono">${Number(item.score).toFixed(4)}</span></strong>
          <span class="meta">${esc(source.title || source.kind || "")}</span>
        </div>
        <div class="content">${esc(item.content)}</div>
        <div class="meta">${esc(item.load_more_uri || "")}</div>
      </div>`;
    }

    async function createMemory() {
      await api("/api/memories", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          content: $("memoryContent").value,
          scope: $("memoryScope").value,
          category: $("memoryCategory").value
        })
      });
      $("memoryContent").value = "";
      await loadMemories();
    }

    async function loadMemories() {
      const data = await api("/api/memories?status=active");
      $("memoryList").innerHTML = data.map((item) => `<div class="item">
        <div class="item-row">
          <strong>${esc(item.category)} / ${esc(item.scope)}</strong>
          <button class="secondary danger" onclick="deleteMemory('${esc(item.id)}')">Delete</button>
        </div>
        <div class="content">${esc(item.content)}</div>
        <div class="meta">${esc(item.id)}</div>
      </div>`).join("");
    }

    async function loadReview() {
      const data = await api("/api/memories/review");
      $("reviewList").innerHTML = data.map((item) => `<div class="item">
        <div class="item-row">
          <strong>Review · ${esc(item.category)} / ${esc(item.scope)}</strong>
          <span>
            <button class="secondary" onclick="loadRelations('${esc(item.id)}')">Relations</button>
            <button class="secondary" onclick="approveMemory('${esc(item.id)}')">Approve</button>
            <button class="secondary danger" onclick="rejectMemory('${esc(item.id)}')">Reject</button>
          </span>
        </div>
        <div class="content">${esc(item.content)}</div>
        <div class="meta">${esc(item.status)} · ${esc(item.id)}</div>
        <div id="relations-${esc(item.id)}" class="meta"></div>
      </div>`).join("");
    }

    async function loadRelations(id) {
      const data = await api(`/api/memories/${id}/relations`);
      const target = $(`relations-${id}`);
      if (!target) return;
      target.innerHTML = data.map((item) =>
        `${esc(item.relation_type)}: ${esc(item.source_content)} -> ${esc(item.target_content)}`
      ).join("<br />") || "No relations";
    }

    async function deleteMemory(id) {
      await api(`/api/memories/${id}`, { method: "DELETE" });
      await loadMemories();
    }

    async function approveMemory(id) {
      await api(`/api/memories/${id}/approve`, { method: "POST" });
      await loadReview();
      await loadMemories();
    }

    async function rejectMemory(id) {
      await api(`/api/memories/${id}/reject`, { method: "POST" });
      await loadReview();
    }

    async function uploadText() {
      await api("/api/resources/text", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ title: $("textTitle").value, text: $("textBody").value })
      });
      $("textBody").value = "";
      await loadResources();
    }

    async function uploadFile() {
      const file = $("fileInput").files[0];
      if (!file) return;
      const body = new FormData();
      body.append("file", file);
      await api("/api/resources/upload", { method: "POST", body });
      $("fileInput").value = "";
      await loadResources();
    }

    async function uploadUrl() {
      await api("/api/resources/link", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ url: $("urlInput").value })
      });
      $("urlInput").value = "";
      await loadResources();
    }

    async function loadResources() {
      const data = await api("/api/resources?status=ready");
      $("resourceList").innerHTML = data.map((item) => `<div class="item">
        <div class="item-row">
          <strong>${esc(item.title)}</strong>
          <button class="secondary danger" onclick="deleteResource('${esc(item.id)}')">Delete</button>
        </div>
        <div class="meta">${esc(item.mime)} · ${esc(item.source_uri)}</div>
      </div>`).join("");
    }

    async function deleteResource(id) {
      await api(`/api/resources/${id}`, { method: "DELETE" });
      await loadResources();
    }

    async function scanDream(autoCommit) {
      const paths = $("dreamPaths").value.split("\\n").map((item) => item.trim()).filter(Boolean);
      await api("/api/dream/scan", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ paths: paths.length ? paths : null, auto_commit: autoCommit })
      });
      await loadSessions();
      await loadMemories();
    }

    async function loadSessions() {
      const data = await api("/api/dream/sessions");
      $("sessionList").innerHTML = data.map((item) => `<div class="item">
        <div class="item-row">
          <strong>${esc(item.source_name || item.source_app_id)} · ${esc(item.status)}</strong>
          <button class="secondary" onclick="commitSession('${esc(item.id)}')">Commit</button>
        </div>
        <div class="meta">${esc(item.external_session_id)} · turns ${esc(item.turn_count || 0)}</div>
      </div>`).join("");
    }

    async function commitSession(id) {
      await api(`/api/dream/sessions/${id}/commit`, { method: "POST" });
      await loadSessions();
      await loadMemories();
    }

    async function loadJobs() {
      const data = await api("/api/jobs");
      $("jobList").innerHTML = data.map((item) => `<div class="item">
        <div class="item-row">
          <strong>${esc(item.pipeline)} · ${esc(item.status)}</strong>
          <span class="mono">${esc(item.attempts)}</span>
        </div>
        <div class="meta">${esc(item.stage)} · ${esc(item.id)}</div>
        <div class="meta">${esc(item.error || "")}</div>
      </div>`).join("");
    }

    async function runJobs() {
      await api("/api/jobs/run-until-idle", { method: "POST" });
      await loadJobs();
      await loadResources();
      await loadMemories();
    }

    async function rebuildIndex(clear) {
      await api("/api/index/rebuild", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ clear })
      });
      await loadJobs();
    }

    async function syncGraph(external) {
      const data = await api("/api/graph/sync", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ external })
      });
      $("graphStatus").textContent = JSON.stringify(data);
      await loadEpisodes();
    }

    async function loadEpisodes() {
      const data = await api("/api/graph/episodes");
      $("graphList").innerHTML = data.map((item) => `<div class="item">
        <div class="item-row">
          <strong>${esc(item.target_type)} · ${esc(item.name)}</strong>
          <span class="meta">${esc(item.external_status)}</span>
        </div>
        <div class="content">${esc(item.body).slice(0, 500)}</div>
        <div class="meta">${esc(item.group_id)} · ${esc(item.id)}</div>
      </div>`).join("");
    }

    async function searchGraph() {
      const query = $("graphQuery").value.trim();
      if (!query) return;
      const data = await api(`/api/graph/entities/search?query=${encodeURIComponent(query)}`);
      $("graphList").innerHTML = data.map((item) => `<div class="item">
        <div class="item-row">
          <strong>${esc(item.entity_text)}</strong>
          <span class="meta">${esc(item.entity_type)}</span>
        </div>
        <div class="meta">${esc(item.episode_name)} · ${esc(item.target_type)}:${esc(item.target_id)}</div>
      </div>`).join("");
    }

    refreshHealth();
    loadMemories();
    loadResources();
    loadSessions();
    loadJobs();
  </script>
</body>
</html>
"""
