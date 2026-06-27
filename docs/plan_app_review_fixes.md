# Plan: App review remediation (DBSPEND360)

Branch: `fix/app-review-findings` (off `main`, working tree clean at creation).
Scope: Fix all findings from the code review of the four dashboard tabs (Job
Clusters, All-Purpose, Instance Pools, Pipeline Compute) plus the shared backend
routers. **No implementation in this doc — this is the design/spec only.**

All file:line references below were verified against the current tree on this
branch. Where the original review was slightly off (location or already
mitigated), a `NOTE` calls it out so nothing is fixed blindly.

---

## How to use this plan

- Work top-down by phase. Phases are ordered by severity and by dependency
  (shared helpers first so later phases just call them).
- Every item has: **Finding → Evidence (file:line) → Fix → Verify**.
- "Verify" steps assume the dev server is running via
  `nohup ./watch.sh > /tmp/databricks-app-watch.log 2>&1 &` (per CLAUDE.md —
  never run uvicorn directly). Backend changes are confirmed with `curl`;
  frontend with the browser + a TypeScript build (`bun run build` in `client/`).
- After backend signature/response changes, regenerate the TS client
  (`./watch.sh` does this automatically; otherwise
  `uv run python scripts/make_fastapi_client.py`).
- Run `./fix.sh` before any commit.

### Global acceptance criteria

1. `cd client && bun run build` passes (no TS errors, no unused-import errors).
2. `uv run ruff check server/` passes.
3. No `dangerouslySetInnerHTML` with unsanitized input remains.
4. Sending `start_date > end_date` to any of the four broken endpoints returns
   HTTP **400** (not 500).
5. The three debug endpoints are gone (or gated) and return 404 in production
   config.

---

## Phase 0 — Shared helpers (do these first; later phases depend on them) ✅ DONE

These are new small utilities so we fix each class of bug **once** and reuse.

> **Status (DONE):** All four helpers landed. `parseCalendarDate` /
> `formatCalendarDate` / `closeOnly` added to `client/src/lib/utils.ts`;
> `formatCurrency` (NaN-safe) added to `client/src/lib/pipeline-display.ts`;
> `react-markdown` installed (via `npm`, since `bun` isn't available in this
> env) and `client/src/components/AnalysisMarkdown.tsx` created. `npm run build`
> **[CORRECTION — see Phase 2 note]** the initial install landed `react-markdown@10`
> in the **repo-root** `node_modules` (pulling `react@19`), which crashed at
> runtime against the client's `react@18`. Phase 2's browser pass caught it; it
> was relocated to `client/` as `react-markdown@^9` and the root copy removed.
> (vite) passes clean. Helpers are not yet wired into call sites — that happens
> in Phases 2–7 as planned.

### 0.1 Date formatting helper (fixes the root of #6) — ✅ done

**Why:** `new Date('YYYY-MM-DD')` parses as UTC midnight; `date-fns format` /
`toLocaleDateString` then render in local time, rolling back a day in negative-UTC
zones. The correct anchor (`T00:00:00`) already exists in `InstancePoolsTable.tsx:83`
and `PipelinesTable.tsx:69` but is not shared.

**Fix:** Add to `client/src/lib/utils.ts` (already exists):

```ts
// Parse a YYYY-MM-DD calendar date as LOCAL midnight, never UTC midnight,
// so display never rolls back a day in negative-UTC timezones.
export function parseCalendarDate(dateStr: string): Date {
  return new Date(`${dateStr}T00:00:00`);
}

export function formatCalendarDate(
  dateStr: string,
  opts: Intl.DateTimeFormatOptions = { year: 'numeric', month: 'short', day: 'numeric' },
): string {
  try {
    return parseCalendarDate(dateStr).toLocaleDateString('en-US', opts);
  } catch {
    return dateStr;
  }
}
```

Used by Phase 3 (#6) everywhere.

### 0.2 Markdown/sanitize helper (fixes the root of #7) — ✅ done

**Why:** 4 sites inject LLM output as HTML after a regex-only markdown pass with
**no** sanitizer. No markdown lib or DOMPurify is currently a dependency
(verified in `client/package.json`).

**Fix (recommended):** Add a real, safe renderer instead of regex + raw HTML.

- `cd client && bun add react-markdown` (sanitizes by default — does not render
  raw HTML unless `rehype-raw` is added, which we will NOT add).
- Create `client/src/components/AnalysisMarkdown.tsx`:

```tsx
import ReactMarkdown from 'react-markdown';

export function AnalysisMarkdown({ children }: { children: string }) {
  return (
    <div className="text-sm leading-relaxed prose prose-sm dark:prose-invert max-w-none">
      <ReactMarkdown>{children}</ReactMarkdown>
    </div>
  );
}
```

**Alternative if avoiding a dep is required:** `bun add dompurify` and wrap the
existing regex output: `dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(html) }}`.
Prefer `react-markdown` — it removes the brittle regex entirely and renders the
`**bold**` / `##` / `###` the LLM already emits.

> Decision: go with `react-markdown` unless the user objects. The emoji `<span>`
> coloring in the cluster modal (`JobBreakdownModal.tsx:739`) is cosmetic and can
> be dropped; emoji render fine as plain text.

### 0.3 Dialog onClose helper (fixes #11) — ✅ done

**Why:** Every `<Dialog onOpenChange={onClose}>` passes Radix's boolean straight
into a `() => void`. Harmless today (only matters on open) but brittle.

**Fix:** Either inline `onOpenChange={(open) => { if (!open) onClose(); }}` at
each of the 6 sites (below), or add a tiny helper in `lib/utils.ts`:

```ts
export const closeOnly = (onClose: () => void) => (open: boolean) => {
  if (!open) onClose();
};
```

Sites (Phase 3, #11): `JobBreakdownModal.tsx:103`, `JobBreakdownModal.tsx:458`,
`InstancePoolDetailsModal.tsx:88`, `PipelineDetailsModal.tsx:91`,
`OtherCostBreakdownModal.tsx:79`.

### 0.4 NaN-safe currency (supports #15 + general robustness) — ✅ done

Add to `client/src/lib/pipeline-display.ts` (or `utils.ts`) a guarded formatter
and reuse in pipeline components:

```ts
const usd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD',
  minimumFractionDigits: 2, maximumFractionDigits: 2 });
export const formatCurrency = (n: number) => usd.format(Number.isFinite(n) ? n : 0);
```

---

## Phase 1 — Critical backend (#1, #8) ✅ DONE

> **Status (DONE):** All four broken endpoints now return **400** on an
> inverted date range (verified via curl: `job-spends`, `grouped-job-spends`,
> `summary`, `top-jobs` all → 400, was 500). Every client-facing `str(e)` leak
> across all five routers (`dashboard.py`, `all_purpose.py`,
> `instance_pools.py`, `pipelines.py`, `user.py`) is genericized — the body is
> now e.g. `{"detail":"Failed to retrieve summary metrics"}` while the full
> traceback is `logger.exception`-logged server-side (`user.py` gained a logger).
> The three debug/diagnostic endpoints (`/api/debug-environment`,
> `/api/debug-table`, `/api/test-connection`) were **deleted** (nothing in the
> frontend called them; only the auto-generated client referenced them) and now
> return 404. 1.4 is documentation-only (no code change). All five routers
> compile clean.

### 1.1 (#1) Date-validation 400 silently turned into 500 — 4 endpoints — ✅ done

**Evidence (`server/routers/dashboard.py`), all confirmed BROKEN:**

| Endpoint | Func (line) | 400 raised | Catch-all (no guard) |
|---|---|---|---|
| `GET /api/job-spends` | `get_job_spends` (47) | 62–66 | 83–87 |
| `GET /api/grouped-job-spends` | `get_grouped_job_spends` (91) | 106–110 | 127–131 |
| `GET /api/summary` | `get_summary_metrics` (173) | 184–188 | 199–203 |
| `GET /api/top-jobs` | `get_top_jobs` (243) | 260–264 | 276–280 |

The other routers (`all_purpose.py`, `instance_pools.py`, `pipelines.py`) and
two dashboard endpoints (`get_job_runs:134`, `get_other_cost_breakdown:646`)
already do `except HTTPException: raise` first — use them as the template.

**Fix:** In each of the four blocks, insert before the catch-all:

```python
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error retrieving ...")   # add server-side log (see 1.3)
        raise HTTPException(status_code=500, detail="...")  # generic (see 1.2)
```

> Optional cleanup (nice-to-have, not required): extract a module-level
> `_validate_date_range(start, end)` helper like `all_purpose.py:59` so the four
> endpoints share one validator. Keep behavior identical.

**Verify (curl, after restart):**

```bash
curl -s -o /dev/null -w "%{http_code}\n" \
  "http://localhost:8000/api/job-spends?start_date=2025-02-01&end_date=2025-01-01"
# expect 400 (was 500)
```
Repeat for `/api/grouped-job-spends`, `/api/summary`, `/api/top-jobs`. Also
confirm a valid range still returns 200.

### 1.2 (#8a) Stop leaking internals in error responses — ✅ done

**Evidence:** 39 client-facing `detail=f"...{str(e)}"` / `str(e)` sites across
routers (dashboard 13 HTTPException + 7 JSON-body; all_purpose 5; instance_pools 6;
pipelines 6; user 2). Full line list in the appendix.

**Fix:** Replace the client-facing message with a generic string and move the
detail to a server-side log. Pattern:

```python
    except Exception:
        logger.exception("Error retrieving job spending data")
        raise HTTPException(status_code=500, detail="Failed to retrieve job spending data")
```

- Do this for **every** `detail=f"...{str(e)}"` in all five routers
  (`dashboard.py`, `all_purpose.py`, `instance_pools.py`, `pipelines.py`,
  `user.py`).
- For the analyze endpoints that embed upstream failure objects
  (`instance_pools.py:268`, `pipelines.py:331` — `str(pool_details)` /
  `str(pipeline_details)`), keep the 500/appropriate status but log the object
  and return a generic message.
- `all_purpose/instance_pools/pipelines` already call `logger.exception` — just
  change the returned `detail` to generic text. `dashboard.py` and `user.py`
  need both the log added and the message genericized.

> NOTE: This intentionally changes response bodies. The frontend only ever
> renders `error.message` / `errorData.detail` as a string
> (`lib/api-client.ts:38`), so generic messages are fine; no TS client
> regeneration needed (status codes/shapes unchanged).

**Verify:** Force an error (e.g. point a bad table name in a scratch run, or
temporarily) and confirm the JSON `detail` no longer contains SQL/host/stack,
while `/tmp/databricks-app-watch.log` shows the full traceback.

### 1.3 (#8b) Remove (or gate) the debug/test endpoints — ✅ done (deleted)

**Evidence (`server/routers/dashboard.py`), no auth, no gating:**

- `GET /api/debug-environment` (391) — leaks `DATABRICKS_HOST` value,
  client-id presence + 10-char prefix, client host internals.
- `GET /api/debug-table` (422) — leaks `service.table_name`,
  `SELECT * ... LIMIT 5` sample rows, min/max dates, filter SQL.
- `GET /api/test-connection` (719) — leaks host, token presence, `.env.local`
  existence, current user, warehouse list, table name, `SELECT 1`/`COUNT(*)`.
- A config flag `enable_debug_endpoints` exists
  (`server/config/config_loader.py:228`, `config/app.dev.config:60`) but is
  **never referenced**.

**Fix (recommended): delete all three endpoints.** They are pure diagnostics and
nothing in the frontend calls them (verify with a repo grep for the paths before
deleting). 

**Alternative (if the user wants to keep them for local dev): gate them.**
Wrap each behind the existing flag:

```python
from server.config.config_loader import load_config  # or however it's exposed
if load_config().enable_debug_endpoints:
    @router.get("/debug-environment")
    async def debug_environment(): ...
```

…so they only register when `enable_debug_endpoints=true` (dev config), and 404
in prod.

> Keep the health endpoints (`/api/health`, etc.) — they expose nothing
> sensitive.
> NOTE: `debug_environment` also imports a non-existent
> `get_databricks_service` from `server.services.databricks_service` (the real
> factory is router-local) — another reason to just delete it.

**Verify:**
```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/api/debug-table
# expect 404 in prod config (or when deleted)
```

### 1.4 (#8c) Auth context (document, no code change required) — ✅ noted

**Evidence:** No FastAPI `Depends`/auth middleware anywhere; CORS is
`allow_origins=['*']` with `allow_credentials=False` (`server/app.py:52`). The
app relies entirely on **Databricks Apps OAuth at the platform proxy**.

**Fix:** No per-endpoint auth is added in this pass (out of scope / would need
product decision). The debug-endpoint removal (1.3) is the concrete security
win. Note in the PR description that data endpoints are gated only by the
Databricks Apps OAuth proxy, so any authenticated workspace user can reach them.

---

## Phase 2 — Critical frontend correctness (#3, #2, #7) ✅ DONE

> **Status (DONE):** 2.1 — `GroupedJobTable.tsx` now imports `Fragment` and the
> mapped row uses `<Fragment key={row.id}>` (the redundant inner-row `key` was
> removed). 2.2 — added a `pkey(p) = `${workspace_id}:${pipeline_id}`` composite
> key in both `PipelinesTable.tsx` (expansion set membership, `togglePipeline`,
> Fragment key, expanded-row key, and per-day key prefix) and
> `PipelineSummaryCards.tsx` (top-5 list key); `GroupedPipeline` carries
> `workspace_id`, and top-5 returns `GroupedPipeline[]`, so the field is always
> available. 2.3 — all four `dangerouslySetInnerHTML` regex chains
> (`JobBreakdownModal` job + cluster analysis, `InstancePoolDetailsModal`,
> `PipelineDetailsModal`) were replaced with `<AnalysisMarkdown>` (Phase 0.2),
> removing the XSS surface. `npm run build` (vite) passes clean; no lint errors.
>
> **Browser pass (headless Playwright, `claude_scripts/phase2_browser_pass.mjs`):**
> 2.1/2.2 — expanding the job table (expand + re-sort) and expanding all 25
> pipeline rows produced **zero** React key warnings in the console. 2.3 —
> intercepted every `/analyze` response and injected a hostile payload
> (`<img src=x onerror=…>` + `<script>`); the modal renders the markdown
> (`**bold**` → `<strong>`, `##` → headings) while the raw HTML is shown as
> **escaped literal text** and never executes (`window.__xss` stays unset, no
> `img[onerror]` in the DOM).
>
> **Regression found & fixed during the pass:** Phase 0.2 had `npm add`ed
> `react-markdown@10` into the **repo-root** `node_modules` (it was in the root
> `package.json`), which pulled in `react@19` as a peer. The client app is
> `react@18`, so react-markdown's elements were created by a *different* React
> instance → runtime crash ("Objects are not valid as a React child … in the
> `<Markdown>` component"). Vite's build doesn't execute, so this slipped past
> the earlier build check. Fix: installed `react-markdown@^9` into `client/`
> (resolves the client's single `react@18`) and removed the stray root
> dependency (root `react@19` pruned). Both `npm run build` and the re-run
> browser pass are green afterward.

### 2.1 (#3) Missing key on mapped fragment — Job table — ✅ done

**Evidence:** `GroupedJobTable.tsx:573-576` — `.map()` returns bare `<>`; key is
on the inner `<TableRow key={row.id}>`.

**Fix:** `import { Fragment } from 'react'` and use
`<Fragment key={row.id}>…</Fragment>` for the mapped element; remove the now
redundant `key` juggling (keep `key` on the Fragment, not the inner row).

**Verify:** Expand a job row, change sort, confirm no React key warning in
console and expansion stays on the correct row.

### 2.2 (#2) Pipeline row key collision across workspaces — ✅ done

**Evidence:** Rows/expansion keyed by `pipeline_id` only:
- `PipelinesTable.tsx:252` `<Fragment key={pipeline.pipeline_id}>`
- `:243` `expandedPipelines.has(pipeline.pipeline_id)`, `:258`
  `togglePipeline(pipeline.pipeline_id)`, toggle fn `:184`
- `:360` `key={...-expanded}`, `:507` per-day key `${pipeline_id}|${usage_date}`
- Top-5 list lives in **`PipelineSummaryCards.tsx:337`** (`key={pipeline.pipeline_id}`),
  NOT in `PipelinesTable` (review said "table and top-5 list" — top-5 is in the
  summary cards).
- `workspace_id` is available (used for the modal at `PipelinesTable.tsx:437`).

> NOTE: DLT `pipeline_id`s are globally-unique GUIDs, so a real collision is
> very unlikely; this is a correctness/consistency fix, lower urgency than the
> equivalent job-id case. Still do it.

**Fix:** Introduce a composite key helper and use everywhere a pipeline is
keyed/tracked:

```ts
const pkey = (p: { workspace_id?: string; pipeline_id: string }) =>
  `${p.workspace_id ?? ''}:${p.pipeline_id}`;
```

- `PipelinesTable.tsx`: change `expandedPipelines` membership + `togglePipeline`
  to take `pkey(pipeline)`; Fragment key, expanded-row key, and per-day key
  prefix all use `pkey`.
- `PipelineSummaryCards.tsx:337`: top-5 `key={pkey(pipeline)}`.

**Verify:** No duplicate-key warnings; expanding one pipeline never toggles
another.

### 2.3 (#7) XSS — sanitize LLM output in all 4 modal sites — ✅ done

**Evidence (all unsanitized):** `JobBreakdownModal.tsx:373` (job analysis),
`JobBreakdownModal.tsx:741` (cluster analysis),
`InstancePoolDetailsModal.tsx:365`, `PipelineDetailsModal.tsx:393`.

**Fix:** Replace each `dangerouslySetInnerHTML` block with
`<AnalysisMarkdown>{analysis.analysis}</AnalysisMarkdown>` (Phase 0.2). Delete
the regex chains. Keep the surrounding container styling.

**Verify:** Open each analysis modal; bold/headers still render; inspect that no
raw HTML is injected. Optionally test with a crafted analysis string containing
`<img src=x onerror=alert(1)>` (via a stubbed response) and confirm it does not
execute.

---

## Phase 3 — Cross-cutting fixes (apply once across all four tabs) ✅ DONE

### 3.1 (#4) SummaryCards never show an error state — ✅ done

**Evidence:** All four destructure only `data` + `isLoading`; `!metrics`
renders the same "No data" as a real empty result:
- `SummaryCards.tsx:21-22`, empty at `:48-68`, top-5 at `:318-357`
- `AllPurposeSummaryCards.tsx:55-60`, empty `:62-92`, top lists `:329-373`/`:383-422`
- `InstancePoolsSummaryCards.tsx:68-73`, empty `:75-105`, top `:273-322`
- `PipelineSummaryCards.tsx:73-81`, empty `:83-113`, top `:325-381`

**Fix:** In each, also destructure `isError`/`error` from the metrics hook (and
the top-N hooks), and add an explicit error branch **before** the `!metrics`
empty branch:

```tsx
if (isMetricsError) {
  return <ErrorState message="Couldn't load …" onRetry={() => refetch()} />;
}
```

- Add a small shared `ErrorState` component (e.g. in `components/ui` or inline)
  with an AlertTriangle, the message, and a Retry button wired to the query's
  `refetch`. Reuse across all four.
- Do the same for the top-N sub-sections (show an inline error + retry instead
  of "No X found").

**Verify:** Stop the backend (or temporarily make the summary endpoint 500) and
confirm each tab's KPI strip shows an error + retry, distinct from an empty date
range; Retry refetches.

### 3.2 (#5) Pagination reset races with the query — ✅ done (key-remount)

**Evidence:** Every table resets page in a `useEffect` that runs *after* the
render that already fired the query with `{ old page, new filters }`; all hooks
use `placeholderData: keepPreviousData`, so the user briefly sees the wrong
slice:
- `GroupedJobTable.tsx:184-187` (pageIndex reset) + hook `useGroupedJobSpends.ts:53-59`
- `AllPurposeClustersTable.tsx:160-166` + `useAllPurposeClusters.ts:44-50`
- `AllPurposeUsersTable.tsx:74-82` + `useAllPurposeClusters.ts:90-97`
- `InstancePoolsTable.tsx:175-185` + `useInstancePools.ts:48-54`
- `PipelinesTable.tsx:159-166` + `usePipelines.ts:43-49`

**Fix (preferred — reset synchronously in the change handler, not an effect):**
Move `setPage(1)` / `setPagination(p => ({...p, pageIndex:0}))` into the same
event handler that changes the search term / date range / workload selection, so
page resets in the same render pass as the filter change. Where filters come in
as props (date range from the dashboard), derive a reset by including the filter
in the query key and resetting via the setter inside the search `onChange` and
binding date-range changes through a wrapper handler in the parent
(`*Dashboard.tsx`) that resets the child's page.

**Fix (simpler, acceptable alternative — key remount):** Give each table a
`key` derived from its filters in the parent dashboard, e.g.
`<GroupedJobTable key={`${start}|${end}|${jobFilter}`} … />`, so a filter change
remounts the table with `page=1` and a fresh expansion set (also solves #9 for
free). Trade-off: loses `keepPreviousData` smoothness on filter change (fine —
we *want* a clean reset there; keepPreviousData still helps for page-to-page
navigation within the same filter).

> Decision: use the **key-remount** approach for filter/date changes (it kills
> #5 and #9 together and is hard to get wrong), and keep `keepPreviousData` for
> intra-filter pagination. Verify the debounced search (All-Purpose) still feels
> smooth; if remount-on-every-keystroke is janky, switch those two tables to the
> synchronous-handler approach instead.

**Verify:** On each table, go to page 3, then change the date range/search;
confirm it jumps to page 1 immediately with correct data and never flashes the
old page-3 slice.

### 3.3 (#9) Expansion state not cleared on filter/date change — ✅ done (via remount)

**Evidence:** No table clears its expansion `Set` on filter change:
- `GroupedJobTable` `expandedRows` (`:182`), `AllPurposeClustersTable`
  `expandedRows` (`:147`), `AllPurposeUsersTable` `expandedRows` (`:69`),
  `InstancePoolsTable` `expandedPools` + `expandedDays` (`:165-166`),
  `PipelinesTable` `expandedPipelines` (`:152`).

**Fix:** If using the key-remount approach in 3.2, this is solved automatically
(fresh state on remount). Otherwise, clear the set in the same handler/effect
that resets the page:
```ts
setExpandedRows(new Set());   // and expandedDays for pools
```

**Verify:** Expand several rows, change the date range; all rows collapse and no
stale lazy queries fire.

### 3.4 (#6) Date display off-by-one in negative-UTC timezones — ✅ done

**Evidence:** `format(new Date(dateStr), …)` in all four FilterControls summary
texts: `FilterControls.tsx:62-67/162`,
`AllPurposeClusterFilterControls.tsx:65-70/160`,
`InstancePoolFilterControls.tsx:69-74/159`,
`PipelineFilterControls.tsx:101-106/192`. Plus deleted-badge formatters using
`new Date(d).toISOString().slice(0,10)`: `InstancePoolsTable.tsx:99-106` and
`PipelinesTable.tsx:83-90`; and modal delete banners using
`toLocaleDateString` without anchor: `InstancePoolDetailsModal.tsx:56-66`,
`PipelineDetailsModal.tsx:57-67`.

**Fix:** Replace every `formatDisplayDate`/`formatBadgeDate`/`formatDeleteDate`
body with `formatCalendarDate` (Phase 0.1). For badges that want ISO output,
use `parseCalendarDate(d)` then format locally instead of `toISOString()`. Drop
the now-duplicated local helpers; import from `lib/utils`.

> NOTE: `<Input type="date">` values bind to raw `YYYY-MM-DD` and are unaffected
> — only the human-readable summary/badge text needs the fix.

**Verify:** Set machine TZ to e.g. `America/Los_Angeles`, pick `2025-03-15`;
the summary and any deleted badge must read `Mar 15, 2025`, not `Mar 14`.

### 3.5 (#11) Dialog `onOpenChange={onClose}` — ✅ done

**Evidence:** 6 sites (Phase 0.3). **Fix:** apply `closeOnly(onClose)` /
inline guard at each. **Verify:** modals still open and close normally.

### 3.6 (#10) Accessibility — every tab — ✅ done

**Evidence/Fix (apply across all tables/modals/filter controls):**
- **Expand/collapse buttons** lack `aria-expanded`: add
  `aria-expanded={isExpanded}` to every chevron toggle button
  (`GroupedJobTable`, `AllPurposeClustersTable`, `AllPurposeUsersTable`,
  `InstancePoolsTable` pool + day toggles, `PipelinesTable`). Some already have
  `aria-label` (e.g. `PipelinesTable:260`) — add `aria-expanded` alongside.
- **Search inputs not tied to labels:** add `id` to each search `<Input>` and
  `htmlFor` to its `<Label>` in the four FilterControls.
- **`<div onClick>` rows/cells** (no keyboard support): the "Other cost" cells
  (`GroupedJobTable.tsx:413`, `AllPurposeClustersTable.tsx:360`,
  `JobBreakdownModal.tsx:276`) and any clickable run/name divs — convert to
  `<button>` (preferred) or add `role="button"`, `tabIndex={0}`, and an
  `onKeyDown` (Enter/Space) handler.
- **Sortable headers** lack `aria-sort`: in `GroupedJobTable` header cells, set
  `aria-sort` based on the column's sort state. (See #J1 — sorting itself is
  also being fixed.)
- **Decorative icons** (search/chevron used purely visually): add
  `aria-hidden="true"`.
- **Tooltip-only explanations:** ensure any info conveyed only via `title=` also
  has an accessible text or `aria-label` equivalent.

**Verify:** Keyboard-only pass (Tab/Enter/Space) can expand rows, open the Other
modal, and focus the search via its label; a screen-reader/inspector shows
`aria-expanded` and `aria-sort` updating.

### 3.7 (refetch consistency — polish) — ✅ done

**Evidence:** Summary/top hooks omit `refetchOnWindowFocus: false` while table
hooks set it. **However** `App.tsx:8-16` sets it globally to `false`, so this is
already effectively applied — behavior is consistent.

**Fix:** Optional only — for explicitness, add `refetchOnWindowFocus: false` to
the summary/top hooks (`useJobSpends.ts:14-20/66-72`,
`useAllPurposeClusters.ts:132-166`, `useInstancePools.ts:91-112`,
`usePipelines.ts:94-116`). No functional change. Low priority.

---

## Phase 4 — Job Clusters tab ✅ DONE

> **Status (DONE):** 4.1 — `/api/grouped-job-spends` + service SQL now take
> `sort_by`/`sort_dir`; `GroupedJobTable` passes its `sorting` state through the
> hook with `manualSorting: true` (no `getSortedRowModel()`), and a sort change
> resets to page 1 — so header clicks sort the full dataset, not just the
> current 50-row page. 4.2 — the job-level "Other" cell is now plain text (the
> mismatched click-through was removed; the `/other-cost-breakdown` endpoint is
> cluster-scoped, so cluster/run-level breakdowns remain the only click-through,
> in `JobBreakdownModal`). 4.3 — `CoverageTrendChart` takes `dateRange` and
> `useCoverageTrend` + `/api/classification-coverage-trend` honor the selected
> range instead of a hardcoded 30 days. 4.4 — one shared `HIGH_COST_USD = 1000`
> in `lib/utils.ts` is used by both the table and the modal, and the runs list
> gained a "Show all" control (`setLimit` up to the endpoint's 100-row cap) with
> an honest "N of M total runs shown" label.

### 4.1 (#J1) Client-side sort over a server-paginated page — ✅ done

**Evidence:** `GroupedJobTable.tsx:506-520` uses `getSortedRowModel()` with no
`manualSorting`; only `manualPagination: true`. Server returns one 50-row page
ordered `total DESC` (`databricks_service.py:641`, `dashboard.py:96`); the hook
sends no sort params (`useGroupedJobSpends.ts:16-21`). So header clicks only
reorder the current 50 rows, misleading users into thinking it's a global sort.

**Fix — choose one:**
- **(A) Honest server-side sort (preferred):** add `sort_by` / `sort_dir` query
  params to `/api/grouped-job-spends` (and the service SQL `ORDER BY`), pass the
  table's `sorting` state through the hook, set `manualSorting: true`, and remove
  `getSortedRowModel()`. Reset to page 1 on sort change (reuse 3.2).
- **(B) Minimal (if backend sort is out of scope):** keep client sort but make
  it honest — either disable column sorting UI (since it's page-local) or add a
  visible note "sorts current page only." Prefer (A).

> Decision: (A). It's the correct behavior and reuses the pagination-reset work.

**Verify:** Sort by a non-default column; confirm the order reflects the full
dataset (top row changes appropriately) and pagination still works.

### 4.2 (#J2) Job-level "Other" cell opens a workspace-wide breakdown — ✅ done (option B)

**Evidence:** `GroupedJobTable.tsx:413` opens the modal with **only**
`dateRange` (`:661-665`) — no `job_id`/`cluster_id`. `OtherCostBreakdownModal`
only accepts `dateRange` + optional `clusterId` (`:22-27`), and
`/api/other-cost-breakdown` filters by cluster, not job. So the breakdown shown
doesn't match the job row.

**Fix — choose one:**
- **(A)** If a job→other breakdown is meaningful: extend the endpoint + service
  + modal to accept `job_id` and filter accordingly; pass `jobId` from the cell.
- **(B)** If not feasible at job grain: remove the click affordance on the
  job-level Other cell (make it plain text), keeping the click-through only where
  a `clusterId` is available (run-level in `JobBreakdownModal:416`, and
  All-Purpose by-cluster). 

> Decision: (B) unless the user wants a real per-job breakdown — the current UX
> is actively misleading. Confirm with user before building (A).

**Verify:** Job-level Other no longer opens a mismatched modal; cluster-scoped
Other still works and matches its row.

### 4.3 (#J3) Coverage trend hardcoded to 30 days — ✅ done

**Evidence:** `CoverageTrendChart.tsx:41-42` calls `useCoverageTrend(30)`;
rendered by `SummaryCards.tsx:365` with no `dateRange`. Hook
`useJobSpends.ts:96`.

**Fix:** Pass `dateRange` from `SummaryCards` → `CoverageTrendChart`; change
`useCoverageTrend` + `/api/classification-coverage-trend` to accept the date
range (or a day-count derived from it) instead of a fixed 30. Keep a sane cap.

**Verify:** Change the dashboard range to 7 / 90 days; the trend chart's x-axis
span changes to match.

### 4.4 (#J4) Inconsistent "High Cost" threshold + runs capped at 10 — ✅ done

**Evidence:** `GroupedJobTable.tsx:495` uses `> 1000`; `JobBreakdownModal.tsx:314`
uses `> 100`. Runs hard-capped at 10 (`GroupedJobTable.tsx:72-76`,
server default `dashboard.py:139`) with label "10 of N shown" (`:97-98`) and no
load-more.

**Fix:**
- Define one shared threshold constant (e.g. `HIGH_COST_USD = 1000`) in a shared
  module and use it in both places (pick the intended value with the user;
  default to 1000).
- Add a "Load more" / "Show all" control to the runs list: bump the
  `useJobRuns` limit on demand (the endpoint already supports `le=100`), or
  paginate. At minimum make the cap obvious and increasable.

**Verify:** Same job shows a consistent High Cost badge in table and modal; runs
list can expand beyond 10.

---

## Phase 5 — All-Purpose tab ✅ DONE

> **Status (DONE):** 5.1 — `AllPurposeClusterFilterControls` is given
> `key={subTab}` so it remounts on sub-tab switch, clearing any pending 300ms
> debounce via the unmount cleanup; a late keystroke can no longer land in the
> switched-to tab. 5.2 — collapsed the two split `<Tabs>` into a single
> `<Tabs value={subTab} onValueChange={handleSubTabChange}>` root spanning the
> header `TabsList` and the body `TabsContent`, so Radix wires
> `aria-controls`/`aria-labelledby` and arrow-key nav works. 5.3 — `subTab`
> initializes from `useState(readSubTabFromUrl)` (no first-render flash) and a
> `popstate` listener re-reads the URL on back/forward. 5.4 — the By-User help
> text is corrected for user rows and the By-User expanded per-cluster rows now
> expose the same clickable Other breakdown (`OtherCostBreakdownModal` with
> `clusterId`) as By-Cluster.

### 5.1 (#A1) Debounced search can commit to the wrong sub-tab — ✅ done

**Evidence:** `AllPurposeClusterFilterControls.tsx:46-50` debounces 300ms;
cleanup only on unmount (`:52-56`). Search state IS per-sub-tab already
(`AllPurposeDashboard.tsx:56-75`), but switching sub-tabs
(`handleSubTabChange`) doesn't cancel a pending timeout, so a late keystroke can
write into the newly-active tab's setter.

> NOTE: the review framed this as "lands in the other sub-tab's state"; because
> `setActiveSearch` is resolved at fire time, the stale value lands in the
> *switched-to* tab. Either way it's wrong — fix the same way.

**Fix:** Cancel the pending debounce when the sub-tab changes. Simplest: give
`AllPurposeClusterFilterControls` a `key={subTab}` so it remounts (clearing the
timeout via the unmount cleanup) on switch; or flush/clear `debounceRef` in
`handleSubTabChange`; or debounce per-tab and ignore writes whose tab !== active.

**Verify:** Type quickly in By Cluster, switch to By User within 300ms; the By
User search must remain empty/unchanged.

### 5.2 (#A2) Split `<Tabs>` roots break tab a11y — ✅ done

**Evidence:** Two separate `<Tabs>` — triggers in CardHeader
(`AllPurposeDashboard.tsx:107-112`), panels in CardContent (`:119-132`). Radix
can't wire `aria-controls`/`aria-labelledby` across two roots.

**Fix:** Use a single `<Tabs value=… onValueChange=…>` wrapping both the
`<TabsList>` (header) and the `<TabsContent>` panels. If the visual layout needs
the list in the header card and panels in the body card, keep one `<Tabs>` root
spanning both cards (Tabs is just a context provider; the DOM can still be
styled into two cards).

**Verify:** Inspect that `TabsTrigger` has `aria-controls` pointing to the
matching `TabsContent id`; arrow-key tab navigation works.

### 5.3 (#A3) Sub-tab URL is write-only (no popstate) — ✅ done

**Evidence:** Reads `?subtab=` on mount (`AllPurposeDashboard.tsx:26-33/62-64`),
writes via `replaceState` (`:35-46`), but no `popstate` listener; deep-link
flashes default first.

**Fix:**
- Add a `popstate` effect that re-reads `readSubTabFromUrl()` and sets state, so
  back/forward sync.
- Initialize `useState(readSubTabFromUrl())` (lazy initializer) instead of
  defaulting then correcting in an effect, to avoid the initial flash.
- Consider `pushState` (not `replaceState`) on user-initiated switches so
  back/forward actually traverse sub-tabs (optional; align with desired UX).

**Verify:** Deep-link `?subtab=by-user` loads By User with no By Cluster flash;
browser Back returns to the previous sub-tab.

### 5.4 (#A4) By-User help text + missing "Other" affordance — ✅ done

**Evidence:** Help text says "Click a cluster name…" for both
(`AllPurposeDashboard.tsx:101-105`); By User rows are users. By Cluster has a
clickable Other breakdown (`AllPurposeClustersTable.tsx:358-370/477-482`); By
User only shows static "Other: $X" (`AllPurposeUsersTable.tsx:434`).

**Fix:**
- Correct the By-User help string (describe user rows / what clicking does).
- Either add the same clickable Other breakdown to By-User expanded per-cluster
  rows (they have `cluster.cluster_id`, so reuse `OtherCostBreakdownModal` with
  `clusterId`), or intentionally leave it static and remove the implication.
  Prefer adding the affordance for parity.

**Verify:** Help text matches the rows; By-User Other cost is clickable and
matches its cluster.

---

## Phase 6 — Instance Pools tab ✅ DONE

> **Status (DONE):** All in `client/src/components/InstancePoolsTable.tsx`.
> 6.1 — `cloudLabel` is now threaded into `DayClusterBreakdown` (alongside the
> existing `PoolDayBreakdown` thread) and replaces the literal `EC2` header in
> the per-cluster drill-down, so it reflects the platform (`EC2 / EBS` on AWS,
> `Total <compute_service>` otherwise). 6.2 — `togglePool` now prunes that pool's
> `expandedDays` keys (prefixed `${poolId}|`) on collapse, and the filter-change
> effect clears both `expandedPools` and `expandedDays` so a date/search change
> never restores stale day drill-downs. 6.3 — the per-day sort is wrapped in
> `useMemo(..., [pool.days])` instead of re-sorting every render, and the
> duplicate `ChevronRight as ChevronRightIcon` import was removed (standardized
> on `ChevronRight` at both former call sites). Eager `/grouped` payload loading
> is deferred per the plan decision (cheap wins only). `npm run build` (vite)
> passes clean; no lint errors.

### 6.1 (#P1) Hardcoded "EC2" header in nested cluster drill-down

**Evidence:** `InstancePoolsTable.tsx:629-635` hardcodes `EC2` while the pool
header and day summary use dynamic `cloudLabel` (`:160-162/243/571`). Wrong on
Azure/GCP.

**Fix:** Pass `cloudLabel` (already threaded as a prop at `:377`) into
`DayClusterBreakdown` and use it for that header cell instead of the literal
`EC2`. (Use the short form, matching the column width — e.g. the cloud compute
service label.)

**Verify:** On an Azure/GCP config (or by mocking `cloudConfig.compute_service`)
the drill-down header reflects the platform, not "EC2".

### 6.2 (#P2) `expandedDays` is global, not per-pool

**Evidence:** `InstancePoolsTable.tsx:165-166` two table-level Sets; day key is
`${pool_id}|${usage_date}` (`:538`) but shared across pools (`:377`). Collapsing
and re-expanding a pool restores unrelated day expansions (and the keys collide
only if not prefixed — they are prefixed by pool, so the real issue is stale
retention across collapse/expand and filter changes).

**Fix:** Clear a pool's day-keys when the pool collapses (filter `expandedDays`
to drop entries starting with that `pool_id|`), and clear all on filter change
(3.3 / key-remount). Optionally scope `expandedDays` per pool via a
`Map<poolId, Set<date>>`. Simplest correct fix: on `togglePool` collapse, prune
matching day keys.

**Verify:** Expand pool A days, collapse A, expand A again — no days are
pre-expanded; expanding pool B doesn't show A's day state.

### 6.3 (#P3) Eager full payload + re-sort every render + duplicate import

**Evidence:**
- `/grouped` returns full `days[]` (+ nested `clusters[]`) for every pool up
  front (`types/instance-pool.ts:76-80`, `databricks_service.py:2904-2924`); UI
  reads `pool.days` directly with no lazy fetch.
- `[...pool.days].sort(...)` recomputed every render
  (`InstancePoolsTable.tsx:535-537`).
- Duplicate import: `ChevronRight` and `ChevronRight as ChevronRightIcon`
  (`:37-40`).

**Fix:**
- **Re-sort:** wrap in `useMemo(() => [...pool.days].sort(...), [pool.days])`.
- **Duplicate import:** remove the redundant alias; use one identifier
  (standardize on `ChevronRight`, update the two usages at `:294`/`:437`).
- **Eager loading:** larger change — defer. Options: (a) add a lazy
  `/api/instance-pools/{id}/days` fetched on expand and drop `days[]` from
  `/grouped`; or (b) keep eager but ensure payload size is acceptable. 
  > Decision: do the cheap wins (memo + import) now; treat lazy-load as a
  > follow-up only if pages are actually heavy (measure first). Note it in the
  > PR as known/optional.

**Verify:** `bun run build` clean (no duplicate-import lint); expanding pools is
smooth; React profiler shows the sort not re-running on unrelated renders.

---

## Phase 7 — Pipeline Compute tab ✅ DONE

> **Status (DONE):** 7.1 — analysis is gated on resolved details
> (`enabled: detailsResolved` in `PipelineDetailsModal`), so it no longer
> fires/charges the LLM while details are ambiguous/failed, and a 409 surfaces a
> friendly message (the table already passes `workspace_id`, so the common path
> doesn't 409 — minimum-viable per the plan decision; full workspace-picker left
> as the optional follow-up). 7.2 — the dashboard's date-range change handler now
> calls `setSelectedWorkloads([])`, so a stale chip can't keep filtering
> invisibly across ranges. 7.3 — the chip helper copy was reworded to OR
> semantics ("chips are an OR filter, so selecting more shows more"). 7.4 — both
> inline formatters were replaced with the shared NaN-safe `formatCurrency`
> (Phase 0.4) from `lib/pipeline-display`.

### 7.1 (#PC1) 409 ambiguous pipeline_id has no disambiguation UX — ✅ done (minimum viable)

**Evidence:** `PipelineDetailsModal.tsx:100-107` shows the raw
`detailsError.message`; server 409 (`pipelines.py:98-105`) says "pass
workspace_id to disambiguate" but there's no workspace picker. Analysis
(`usePipelineAnalysis`) fires regardless of details state
(`PipelineDetailsModal.tsx:81-85`, `usePipelines.ts:139-148`).

**Fix:**
- The table already knows the `workspace_id` and passes it
  (`PipelinesTable.tsx:434-440`), so the common path won't 409. For robustness:
  detect 409 on details and render a small workspace picker (the server message
  lists workspace ids; better: return them structured — extend the 409 body to
  include `workspace_ids: []` and render buttons). Selecting one re-queries with
  that `workspace_id`.
- **Gate analysis on details:** set `enabled: !!pipelineId && !!workspaceId &&
  !detailsError` (or only after details resolve) so analysis doesn't fire/charge
  LLM when details are ambiguous/failed.

> Decision: minimum viable = gate analysis on successful details + show a
> friendly 409 message; full workspace-picker if the user wants it (needs the
> structured 409 body change).

**Verify:** Force a 409 (pipeline id present in multiple workspaces, call without
workspace_id); modal shows a helpful disambiguation UI and does not fire
analysis.

### 7.2 (#PC2) `selectedWorkloads` not reset on date-range change — ✅ done

**Evidence:** `PipelineDashboard.tsx:31-33` holds `selectedWorkloads`; no reset
when `dateRange` changes. A chip selected in the old range keeps filtering
invisibly.

**Fix:** In the dashboard's date-range change handler, also
`setSelectedWorkloads([])` (and `setSearchTerm('')` if desired). Or surface the
active chips prominently so they're never "invisible." Prefer reset on range
change.

**Verify:** Select a workload chip, change the date range; chips clear and the
table shows unfiltered results for the new range.

### 7.3 (#PC3) Chip copy says "narrows" but server is IN(...) (OR) — ✅ done

**Evidence:** Copy at `PipelineFilterControls.tsx:249-252` says "narrow"; server
builds `AND workload_type IN (...)` (`databricks_service.py:3381-3392`), i.e.
selecting more chips broadens (union). Client appends repeated `workload_type`
params (`lib/api-client.ts:347`).

**Fix:** Reword the helper text to match OR semantics, e.g. "Select one or more
types to include; selecting more shows more." Keep the "never hides spend"
nuance if accurate.

**Verify:** Copy matches observed behavior (more chips → more/equal rows).

### 7.4 (#PC4 / #15) `formatCurrency` has no NaN guard — ✅ done

**Evidence:** Inline formatters `PipelineSummaryCards.tsx:50-57` and
`PipelinesTable.tsx:67` call `Intl…format(amount)` with no finite check.

**Fix:** Replace both with the shared guarded `formatCurrency` (Phase 0.4).

**Verify:** Feed a null/NaN (e.g. missing field) and confirm it renders `$0.00`,
not `$NaN`.

---

## Phase 8 — Lower-priority polish ✅ DONE

> **Status (DONE):** poly1 — removed the unused `TrendingUp`/`TrendingDown`
> imports from `SummaryCards.tsx`. poly2 — `OtherCostBreakdownModal` table rows
> now key by the stable `${source_system}:${service_name}` composite instead of
> the array index (skeleton/chart static-list index keys left as-is per the
> note). poly3 — all four SummaryCards no longer early-return on metrics
> `isLoading`; metrics-derived values are computed null-safely and each
> metrics-dependent section (KPI strip, cost breakdown / pool-metadata /
> workload-breakdown / compute-mode footnote) renders its own skeleton/error,
> while the top-N lists render off their own hook state — so they load
> independently with less layout shift (added small `KpiStripSkeleton` /
> `BreakdownSkeleton` helpers). poly4 — no-op (already effectively false via the
> global `App.tsx` query client, per 3.7). poly5 — added
> `isInvalidDateRange(start, end)` to `lib/utils.ts` and wired it into all four
> FilterControls: when start > end the end-date input gets `aria-invalid` + a red
> border and an inline `role="alert"` message appears immediately (these pickers
> commit on change, so there's no Apply button to disable). `npm run build`
> (vite) passes clean; no lint errors in any edited file.

- **(#poly1) Unused imports:** remove `TrendingDown` (and unused `TrendingUp`)
  from `SummaryCards.tsx:5`. `bun run build` / eslint will confirm. — ✅ done
- **(#poly2) Index-keyed rows** in `OtherCostBreakdownModal.tsx:162-163`
  (`key={idx}`): key by a stable field (e.g. the item's category/cluster id).
  Skeleton/chart index keys (`:97`, `:139`) are low-risk; leave or fix opportunistically. — ✅ done
- **(#poly3) Summary loading blocks whole KPI strip:** the metrics `isLoading`
  early-return hides the top-5 too. Render per-section skeletons (already have
  `TopListSkeleton`) so the strip and top-5 load independently → less layout
  shift. Applies to all four SummaryCards. — ✅ done
- **(#poly4) refetchOnWindowFocus:** see 3.7 (already effectively false via
  global; explicit is optional). — ✅ done (no-op)
- **(#poly5) Client-side `start_date > end_date` guard:** add a cheap validation
  in the date pickers / dashboards so the user gets immediate feedback instead of
  relying on the API (now correctly 400 after Phase 1.1). Disable Apply or show
  inline error when start > end. — ✅ done (inline error)

---

## Suggested commit/PR slicing

1. **PR 1 — backend hardening** (Phase 1: #1 + #8). Self-contained, curl-verified.
2. **PR 2 — critical FE correctness + XSS** (Phase 2 + Phase 0.2).
3. **PR 3 — cross-cutting** (Phase 3 + Phase 0.1/0.3/0.4): error states,
   pagination/expansion, dates, dialog, a11y.
4. **PR 4 — per-tab** (Phases 4–7), optionally one PR per tab.
5. **PR 5 — polish** (Phase 8).

(Or one branch/PR if the user prefers; phases still define commit boundaries.)

---

## Coverage check — every review finding is addressed

| Review # | Title | Plan item |
|---|---|---|
| 1 | 400→500 on 4 endpoints | 1.1 |
| 2 | Pipeline key collision | 2.2 |
| 3 | Missing fragment key (jobs) | 2.1 |
| 4 | SummaryCards no error state | 3.1 |
| 5 | Pagination reset race | 3.2 |
| 6 | Date off-by-one | 0.1 + 3.4 |
| 7 | XSS / dangerouslySetInnerHTML | 0.2 + 2.3 |
| 8 | Leaks internals + debug endpoints | 1.2 + 1.3 (+1.4 note) |
| 9 | Expansion not cleared | 3.3 (via 3.2 remount) |
| 10 | Accessibility | 3.6 |
| 11 | Dialog onOpenChange | 0.3 + 3.5 |
| Job Clusters: sort | client-side sort | 4.1 |
| Job Clusters: Other cell | wrong scope | 4.2 |
| Job Clusters: coverage | hardcoded 30d | 4.3 |
| Job Clusters: thresholds/runs | inconsistent / cap 10 | 4.4 |
| All-Purpose: debounce | wrong sub-tab | 5.1 |
| All-Purpose: tabs roots | a11y | 5.2 |
| All-Purpose: URL | no popstate | 5.3 |
| All-Purpose: help/Other | copy + affordance | 5.4 |
| Instance Pools: EC2 header | hardcoded | 6.1 |
| Instance Pools: expandedDays | global scope | 6.2 |
| Instance Pools: eager/sort/import | perf + dup import | 6.3 |
| Pipeline: 409 UX | no picker / analysis fires | 7.1 |
| Pipeline: workloads reset | stale filter | 7.2 |
| Pipeline: chip copy | wrong semantics | 7.3 |
| Pipeline: NaN guard | formatCurrency | 7.4 |
| Polish: unused import | TrendingDown | 8 (#poly1) |
| Polish: index keys | OtherCostBreakdownModal | 8 (#poly2) |
| Polish: KPI skeletons | layout shift | 8 (#poly3) |
| Polish: refetch consistency | hooks | 3.7 / 8 (#poly4) |
| Polish: client-side date guard | start>end | 8 (#poly5) |

---

## Appendix — full `str(e)` leak line list (for Phase 1.2)

- `dashboard.py` HTTPException: 86, 130, 168, 202, 238, 279, 387, 544, 574,
  642, 677, 698, 715.
- `dashboard.py` JSON-body (in debug/test endpoints — removed by 1.3): 414,
  475, 744, 752, 765, 779, 797.
- `all_purpose.py`: 93, 132, 171, 202, 232.
- `instance_pools.py`: 114, 159, 192, 225, 268, 297.
- `pipelines.py`: 144, 196, 238, 278, 331, 360.
- `user.py`: 41, 60 (also add a logger — `user.py` has none).
