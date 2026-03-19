# Composite Workspaces Plan

## Context

Roadrunner workspaces are fully isolated — each has its own Neo4j graph namespace, pgvector partition, and PostgreSQL records. The user wants **composite workspaces**: virtual, read-only workspaces that union multiple source workspaces for cross-workspace querying.

**Use case:** "invoices" workspace + "vendor-news" workspace → composite "vendor-analysis" workspace. Ask "Why are my invoices going up?" and the LLM correlates invoice data with vendor news from both graphs.

**Key requirements:**
- N composite workspaces, each referencing any mix of standard or composite workspaces
- Nesting allowed (composite → composite), with cycle detection and max depth 3
- Composites are read-only (no ingestion)
- Entity resolution across sources (Phase 2)

---

## Phase 1: Fan-out Query

### 1.1 Database Schema

**File: `apps/orchestrator/app/db.py`** — Add to `_SCHEMA_TEMPLATE`:

```sql
CREATE TABLE IF NOT EXISTS orchestrator_composite_workspaces (
    name TEXT PRIMARY KEY,
    sources TEXT[] NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Standard workspaces remain implicit (derived from documents/jobs). Only composites have explicit rows.

### 1.2 New Service: `apps/orchestrator/app/services/composite.py`

Core functions:

- **`get_composite(name) -> dict | None`** — Fetch from `orchestrator_composite_workspaces`. Returns `{name, sources, created_at, updated_at}` or `None`.

- **`is_composite(name) -> bool`** — Quick existence check.

- **`resolve_sources(name, depth=0) -> set[str]`** — Recursively flatten a composite to its unique standard workspace names. If `name` is not a composite, returns `{name}`. Raises `ValueError` if depth > 3 (cycle/depth protection).

```python
async def resolve_sources(name: str, depth: int = 0) -> set[str]:
    if depth > 3:
        raise ValueError(f"Composite nesting too deep (max 3)")
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT sources FROM orchestrator_composite_workspaces WHERE name = $1", name
    )
    if not row:
        return {name}  # standard workspace
    result = set()
    for src in row["sources"]:
        result |= await resolve_sources(src, depth + 1)
    return result
```

- **`validate_composite(name, sources)`** — Pre-create/update validation:
  - Sources list must not be empty
  - Name must not appear in sources (direct self-reference)
  - Name must not collide with a standard workspace that has documents
  - Recursively resolve each source — reject if adding this composite creates a cycle or exceeds depth 3

- **`fan_out_query(text, sources, mode, client) -> dict`** — Parallel query via `asyncio.gather`:
  - Calls `archival_memory.query()` for each source workspace
  - Merges results:
    - **Entities**: deduplicate by `entity_name` (case-insensitive), keep longest description. Add `_source_workspace` tag.
    - **Relations**: deduplicate by `(src_id, tgt_id)`. Add `_source_workspace` tag.
    - **Chunks**: concatenate all (already workspace-scoped). Add `_source_workspace` tag.
  - Returns standard `{entities, relations, chunks}` shape.

### 1.3 CRUD Endpoints

**File: `apps/orchestrator/app/routes/workspaces.py`** — Add:

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/v1/workspaces/composite` | Create composite. Body: `{name, sources: [...]}`. Validates cycles/depth/collisions. |
| `PUT` | `/v1/workspaces/composite/{name}` | Update sources. Body: `{sources: [...]}`. Re-validates. |
| `DELETE` | `/v1/workspaces/composite/{name}` | Delete composite definition. Returns 409 if other composites reference it. |
| `GET` | `/v1/workspaces/composite/{name}` | Get composite with `resolved_sources` (flattened). |

**Modify `GET /v1/workspaces`** — After fetching standard workspaces from documents/jobs query, also fetch all composites. For each composite, resolve sources and compute aggregate stats (sum doc_count, sum jobs across sources). Return all workspaces with `type: "standard" | "composite"` field. Composites also include `sources` array.

**Modify `DELETE /v1/workspaces/{workspace}`** — If target is composite, only delete from `orchestrator_composite_workspaces` (no source data touched). Warn if other composites reference it.

### 1.4 Block Ingestion into Composites

**File: `apps/orchestrator/app/routes/documents.py`**

At top of `ingest_document()` and `ingest_codebase()`:
```python
if await is_composite(workspace):
    raise HTTPException(400, "Cannot ingest into composite workspace. Composite workspaces are read-only.")
```

### 1.5 Query Fan-out

**File: `apps/orchestrator/app/routes/data_query.py`**

**`POST /v1/data/query`** — After resolving workspace:
```python
composite = await get_composite(workspace)
if composite:
    sources = await resolve_sources(workspace)
    data = await fan_out_query(request.query, list(sources), mode, _http_client)
else:
    data = await archival_memory.query(request.query, workspace, mode=mode, client=_http_client)
```
Rest of the endpoint works unchanged — `data` has the same `{entities, relations, chunks}` shape.

**`POST /v1/data/explain`** — Same pattern: detect composite, fan-out, then stream. Context formatting is identical.

**`GET /v1/data/weights`** — For composites, query across all resolved sources using `WHERE workspace = ANY($1::text[])`.

**`POST /v1/data/reconcile`** — Block for composites with 400 (read-only).

### 1.6 Frontend: Query Path Fix

**Critical issue:** `queryGraph()` in `api.js` calls LightRAG directly at `${LIGHTRAG}/query/data` with a single `LIGHTRAG-WORKSPACE` header. This bypasses the orchestrator entirely and cannot do fan-out.

**Fix:** Add a new `queryData()` function that goes through the orchestrator:
```javascript
export const queryData = (query, workspace, mode = 'hybrid') =>
  request(`${API}/v1/data/query`, {
    method: 'POST',
    body: JSON.stringify({ query, workspace, mode }),
  });
```

**File: `apps/ingestion-ui/src/components/QueryPanel.jsx`** — Use `queryData()` for composite workspaces, keep `queryGraph()` for standard workspaces (to preserve direct-to-LightRAG performance for non-composite queries). Detect via workspace type from the workspaces list.

### 1.7 Frontend: API Functions

**File: `apps/ingestion-ui/src/api.js`** — Add:
```javascript
export const createCompositeWorkspace = (name, sources) =>
  request(`${API}/v1/workspaces/composite`, {
    method: 'POST',
    body: JSON.stringify({ name, sources }),
  });

export const updateCompositeWorkspace = (name, sources) =>
  request(`${API}/v1/workspaces/composite/${encodeURIComponent(name)}`, {
    method: 'PUT',
    body: JSON.stringify({ sources }),
  });

export const deleteCompositeWorkspace = (name) =>
  request(`${API}/v1/workspaces/composite/${encodeURIComponent(name)}`, {
    method: 'DELETE',
  });
```

### 1.8 Frontend: Dashboard

**File: `apps/ingestion-ui/src/pages/DashboardPage.jsx`**

- Composite workspace cards get distinct styling: dashed purple border, "Composite" badge, list of source workspace names.
- Clicking a composite card navigates to `/query` (not `/ingest`).
- Delete only removes the composite definition.
- Add a "New Composite" creation card alongside the existing "New workspace" card.

**New file: `apps/ingestion-ui/src/components/CompositeWorkspaceDialog.jsx`**

Modal dialog:
- Name input
- Checklist of all existing workspaces (standard + composite, with `[C]` markers)
- At least one source must be selected
- Shows validation errors from API (cycles, depth)

### 1.9 Frontend: Workspace Selector

**File: `apps/ingestion-ui/src/components/WorkspaceSelector.jsx`**

Show `[C]` prefix for composite workspaces in dropdown:
```jsx
<option value={w.name}>{w.type === 'composite' ? '[C] ' : ''}{w.name}</option>
```

### 1.10 Frontend: Ingest Page

**File: `apps/ingestion-ui/src/pages/IngestPage.jsx`** (or equivalent)

When workspace is composite, show banner: "Composite workspace — ingestion disabled. Switch to a source workspace to upload." Hide the drop zone.

### 1.11 Frontend: Documents Page

For composite workspaces, show a read-only merged view:
- Fetch documents from all resolved source workspaces
- Add "Source" column showing which workspace each doc belongs to
- Hide delete/download buttons (read-only)

### 1.12 Frontend: useWorkspaces Hook

**File: `apps/ingestion-ui/src/hooks/useWorkspaces.js`**

Add helper to check if current workspace is composite:
```javascript
export function useIsComposite() {
  const { workspace } = useWorkspace();
  const { workspaces } = useWorkspaces();
  return workspaces.find(w => w.name === workspace)?.type === 'composite';
}
```

---

## Phase 2: Entity Resolution

### 2.1 Database Schema

**File: `apps/orchestrator/app/db.py`** — Add:

```sql
CREATE TABLE IF NOT EXISTS composite_entity_mappings (
    id BIGSERIAL PRIMARY KEY,
    composite_name TEXT NOT NULL REFERENCES orchestrator_composite_workspaces(name) ON DELETE CASCADE,
    source_workspace TEXT NOT NULL,
    source_entity_name TEXT NOT NULL,
    resolved_name TEXT NOT NULL,
    similarity FLOAT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_entity_mappings_composite ON composite_entity_mappings(composite_name);
CREATE UNIQUE INDEX IF NOT EXISTS idx_entity_mappings_unique
    ON composite_entity_mappings(composite_name, source_workspace, source_entity_name);
```

### 2.2 Resolution Service

**New file: `apps/orchestrator/app/services/entity_resolution.py`**

Algorithm:
1. For the composite, resolve to source workspaces
2. Fetch all entity names + embeddings from pgvector for each source
3. Cross-join entities across different workspaces (not intra-workspace)
4. Compute cosine similarity for each pair
5. Threshold 0.85 → candidate matches
6. Secondary check: entity_type must match
7. Union-find to group equivalent entities (reuse pattern from `reconcile.py`)
8. Pick canonical name per group (longest description)
9. Write to `composite_entity_mappings`

Functions:
- `resolve_entities(composite_name, threshold=0.85) -> dict` — Full pipeline, returns `{entities_resolved, groups}`
- `get_entity_mappings(composite_name) -> dict` — Returns `{(workspace, entity_name): resolved_name}` for query-time use

### 2.3 Resolution Endpoint

**File: `apps/orchestrator/app/routes/workspaces.py`** — Add:

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/v1/workspaces/composite/{name}/resolve` | Trigger entity resolution. Returns stats. |

### 2.4 Apply Mappings at Query Time

**File: `apps/orchestrator/app/services/composite.py`**

In `fan_out_query()`, after merging, check if entity mappings exist. If so:
1. Replace entity names with resolved names
2. Update relation src_id/tgt_id to resolved names
3. Re-deduplicate by resolved name

### 2.5 Frontend

- "Resolve Entities" button on composite cards in dashboard
- Show `refreshed_at` timestamp and staleness indicator
- Add `resolveCompositeEntities(name)` to `api.js`

---

## Phase 3: Smart Explain

### 3.1 Source-Aware System Prompt

**File: `apps/orchestrator/app/routes/data_query.py`**

When workspace is composite, modify the explain system prompt:
```
You are analyzing data from multiple knowledge sources: invoices, vendor-news.
When referencing information, indicate which source it comes from.
Look for correlations ACROSS sources — this is the primary value of this composite view.
```

### 3.2 Source-Tagged Context

Modify `_format_context_numbered()` to include source workspace when `_source_workspace` is present:
```
- [FUNCTION] parse_config (from: codebase-ws): Parses YAML configuration files
```

Group chunks by source workspace in the context.

### 3.3 Source Footer

Modify `_format_sources_footer()` to group by workspace:
```
**Sources**
*invoices*
1. **invoice_report.pdf** — Total costs increased 15%...
*vendor-news*
2. **vendor_update.md** — Supplier X announced price increase...
```

### 3.4 Frontend Source Tags

**File: `apps/ingestion-ui/src/components/QueryPanel.jsx`**

For composite results, show source workspace badges on entities, relations, and chunks. Summary banner: "Results from 3 workspaces: invoices (12 entities), vendor-news (8 entities)"

---

## Files Summary

### New files (3):
- `apps/orchestrator/app/services/composite.py` — Core composite logic (Phase 1)
- `apps/orchestrator/app/services/entity_resolution.py` — Entity resolution (Phase 2)
- `apps/ingestion-ui/src/components/CompositeWorkspaceDialog.jsx` — Creation modal (Phase 1)

### Modified files (10):
- `apps/orchestrator/app/db.py` — Schema for both tables
- `apps/orchestrator/app/routes/workspaces.py` — CRUD endpoints, list modification
- `apps/orchestrator/app/routes/data_query.py` — Fan-out query, source-aware explain
- `apps/orchestrator/app/routes/documents.py` — Block ingestion into composites
- `apps/ingestion-ui/src/api.js` — New API functions, `queryData()`
- `apps/ingestion-ui/src/pages/DashboardPage.jsx` — Composite cards, creation UI
- `apps/ingestion-ui/src/components/WorkspaceSelector.jsx` — `[C]` prefix
- `apps/ingestion-ui/src/components/QueryPanel.jsx` — Route composites through orchestrator, source tags
- `apps/ingestion-ui/src/hooks/useWorkspaces.js` — `useIsComposite()` helper
- `apps/ingestion-ui/src/components/DocumentTable.jsx` — Optional source column, read-only mode

---

## Verification

### Phase 1
1. Create composite via `POST /v1/workspaces/composite` — verify it appears in `GET /v1/workspaces` with `type: composite`
2. Attempt ingestion into composite — verify 400 error
3. Query composite via `/v1/data/query` — verify merged results from all sources with `_source_workspace` tags
4. Test cycle detection: A → [B], then try B → [A] — verify error
5. Test nesting: A → [B], C → [A, D] — verify `resolve_sources("C")` returns `{B, D}`
6. Test depth limit: chain of 4 composites — verify rejection
7. Dashboard shows composite cards with distinct styling, sources listed
8. Workspace selector shows `[C]` prefix
9. Ingest page shows read-only banner for composites
10. Explain streams correctly for composite queries

### Phase 2
1. Create two workspaces with overlapping entities (same company, different spelling)
2. Create composite, run `POST /v1/workspaces/composite/{name}/resolve`
3. Verify `composite_entity_mappings` has correct rows
4. Query composite — verify entities merged by resolved name

### Phase 3
1. Query composite, hit Explain — verify LLM references source workspaces
2. Verify source footer groups by workspace
3. Verify frontend shows source badges on results
