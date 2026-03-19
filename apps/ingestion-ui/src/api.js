const API = '/api';
const LIGHTRAG = '/lightrag';

async function request(url, options = {}) {
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  });
  if (res.status === 401) {
    window.location.href = '/login';
    throw new Error('Not authenticated');
  }
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json();
}

function handleAuthRedirect(res) {
  if (res.status === 401) {
    window.location.href = '/login';
    throw new Error('Not authenticated');
  }
  return res;
}

// Workspaces
export const listWorkspaces = () => request(`${API}/v1/workspaces`);

export const deleteWorkspace = (workspace) =>
  request(`${API}/v1/workspaces/${encodeURIComponent(workspace)}`, { method: 'DELETE' });

// Jobs
export const listJobs = (workspace, status, limit = 10000) => {
  const p = new URLSearchParams();
  if (workspace) p.set('workspace', workspace);
  if (status) p.set('status', status);
  p.set('limit', String(limit));
  return request(`${API}/v1/jobs?${p}`);
};

export const getJob = (jobId) => request(`${API}/v1/jobs/${jobId}`);

export const retryJob = (jobId) =>
  request(`${API}/v1/jobs/${jobId}/retry`, { method: 'POST' });

export const prioritizeJob = (jobId) =>
  request(`${API}/v1/jobs/${jobId}/prioritize`, { method: 'POST' });

export const retryFailedJobs = (workspace) =>
  request(`${API}/v1/jobs/retry-failed?workspace=${encodeURIComponent(workspace)}`, { method: 'POST' });

// Documents
export const ingestDocument = (file, workspace, fileName) => {
  const form = new FormData();
  form.append('file', file, fileName || file.name);
  return fetch(`${API}/v1/documents/ingest`, {
    method: 'POST',
    headers: { 'X-Workspace': workspace },
    body: form,
  }).then(handleAuthRedirect).then((r) => r.json());
};

export const ingestCodebase = (file, workspace) => {
  const form = new FormData();
  form.append('file', file);
  return fetch(`${API}/v1/codebase/ingest`, {
    method: 'POST',
    headers: { 'X-Workspace': workspace },
    body: form,
  }).then(handleAuthRedirect).then((r) => r.json());
};

export const deleteDocument = (docId) =>
  request(`${API}/v1/documents/${docId}`, { method: 'DELETE' });

// Delete documents from LightRAG knowledge graph (entities, relations, embeddings)
export const deleteLightragDocs = (docIds, workspace) =>
  request(`${LIGHTRAG}/documents/delete_document`, {
    method: 'DELETE',
    headers: { 'LIGHTRAG-WORKSPACE': workspace, 'Content-Type': 'application/json' },
    body: JSON.stringify({ doc_ids: docIds }),
  });

// Clear entire workspace in LightRAG (all docs, entities, relations, embeddings)
export const clearWorkspace = (workspace) =>
  request(`${LIGHTRAG}/documents`, {
    method: 'DELETE',
    headers: { 'LIGHTRAG-WORKSPACE': workspace },
  });

export const downloadDocumentUrl = (docId) =>
  `${API}/v1/documents/${docId}/download`;

// LightRAG
export const listLightragDocs = (workspace) =>
  request(`${LIGHTRAG}/documents`, {
    headers: { 'LIGHTRAG-WORKSPACE': workspace },
  });

export const queryGraph = (query, workspace, mode = 'naive', opts = {}) => {
  const payload = { query, mode, ...opts };
  // For graph-aware modes, supply keywords from query to skip LLM extraction
  if (mode !== 'naive' && !opts.ll_keywords && !opts.hl_keywords) {
    payload.ll_keywords = [query];
    payload.hl_keywords = [query];
  }
  return request(`${LIGHTRAG}/query/data`, {
    method: 'POST',
    headers: { 'LIGHTRAG-WORKSPACE': workspace, 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
};

export const queryExplainStream = async function* (query, workspace, mode = 'mix') {
  const res = await fetch(`${API}/v1/data/explain`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, workspace, mode }),
  });
  if (res.status === 401) {
    window.location.href = '/login';
    throw new Error('Not authenticated');
  }
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status}: ${text}`);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop();
    for (const line of lines) {
      if (!line.startsWith('data: ')) continue;
      const payload = line.slice(6).trim();
      if (!payload || payload === '[DONE]') continue;
      if (payload[0] === '{') {
        const parsed = JSON.parse(payload);
        const delta = parsed.choices?.[0]?.delta?.content;
        if (delta) yield delta;
      } else {
        yield payload;
      }
    }
  }
};

// Weights (balloon visualization)
export const getWeights = (workspace) =>
  request(`${API}/v1/data/weights?workspace=${encodeURIComponent(workspace)}`);

// Reconcile
export const reconcileGraph = (workspace) =>
  request(`${API}/v1/data/reconcile?workspace=${encodeURIComponent(workspace)}`, {
    method: 'POST',
  });

// Graph
export const getTopGraph = (workspace, limit = 2000) =>
  request(`${API}/v1/graph/top?workspace=${encodeURIComponent(workspace)}&limit=${limit}`);

export const searchGraph = (workspace, q, limit = 200) =>
  request(`${API}/v1/graph/search?workspace=${encodeURIComponent(workspace)}&q=${encodeURIComponent(q)}&limit=${limit}`);

export const getGraphLabels = (workspace) =>
  request(`${LIGHTRAG}/graph/label/list`, {
    headers: { 'LIGHTRAG-WORKSPACE': workspace },
  });

export const getGraphByLabel = (label, workspace) =>
  request(`${LIGHTRAG}/graphs?label=${encodeURIComponent(label)}`, {
    headers: { 'LIGHTRAG-WORKSPACE': workspace },
  });

// Health
export const healthCheck = () => request(`${API}/health`);

// Auth
export const getMe = () => request(`${API}/auth/me`);

export const listApiKeys = () => request(`${API}/auth/api-keys`);

export const createApiKey = (name, rotationDays) =>
  request(`${API}/auth/api-keys`, {
    method: 'POST',
    body: JSON.stringify({ name, rotation_days: rotationDays }),
  });

export const revokeApiKey = (keyId) =>
  request(`${API}/auth/api-keys/${keyId}`, { method: 'DELETE' });
