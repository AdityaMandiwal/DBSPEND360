# Plan — Add a "Pipeline Compute" tab alongside Job Clusters, All-Purpose Clusters, and Instance Pools

Branch (proposed): `feat/pipeline-compute-tab`

> **Naming note.** The user-facing tab is **"Pipeline Compute"** — it covers
> *all* declarative / serverless pipeline-backed compute, not just Lakeflow
> Declarative Pipelines (DLT). The billing key is
> `usage_metadata.dlt_pipeline_id` (Databricks' field name); we surface it as
> `pipeline_id` in our tables and route it under `/api/pipelines/*`. This plan
> supersedes the earlier "DLT Pipelines tab" framing after the §0 materiality
> check proved that `dlt_pipeline_id` spend is **75% non-DLT**.

## 0. Materiality verification (run before CP1 — DONE)

The council's gate question was: *is `dlt_pipeline_id` spend even real in dev,
and is it actually "DLT"?* Both were answered against the dev workspace
(`e2-demo-field-eng`, warehouse `8baced1ff014912d`) for the trailing 30 days
(2026-05-24 → 2026-06-23). Reproduce with
`claude_scripts/dlt_materiality.py` and `claude_scripts/dlt_product_breakdown.py`.

**Gate query result — material.** `usage_metadata.dlt_pipeline_id IS NOT NULL`
returns **2,370 distinct pipelines / 252,548 DBU** over 30 days. The build is
justified; the effort estimate is real (not fiction).

**Full list-cost breakdown by `billing_origin_product` (30-day list price):**

| Workload (`billing_origin_product`) | mode | pipelines | list $/30d | snapshot coverage |
|---|---|---|---|---|
| **SQL** — DBSQL materialized views / streaming tables | serverless | 636 | **$62,778** | 79% (131 missing) |
| **DLT** — Lakeflow Declarative Pipelines | serverless | 1,056 | **$24,071** | 97% (31 missing) |
| **DATABASE** — online tables / Lakebase | serverless | 260 | **$9,641** | 100% |
| **MODEL_SERVING** | classic | 42 | $2,381 | 95% |
| **DLT** | classic | 71 | $1,334 | (folded into DLT) |
| **VECTOR_SEARCH** | serverless | 393 | $704 | **0% (393 missing)** |
| **AI_FUNCTIONS** | classic | 23 | $12 | 100% |
| **Total** | — | **~2,370** | **~$100,921** | 23% missing overall |

**Five findings that shaped this plan:**

1. **DLT is only ~25% of `dlt_pipeline_id` spend; DBSQL materialized views
   (SQL) are 62% — the single biggest bucket.** A tab labelled "DLT Pipelines"
   showing $100K would be false; one showing only $25K would hide $75K of
   pipeline-backed compute that is invisible in *every* other DBSpend360 tab
   (it is excluded from Job and All-Purpose by `cluster_source`, and most of it
   is serverless with no pool). **Decision: go broad and dimension by
   workload type** (§3.1).
2. **96% of the spend is serverless** ($97K of $101K). Classic is only
   MODEL_SERVING ($2,381) + DLT-classic ($1,334) + AI_FUNCTIONS ($12) ≈ $3.7K.
   For serverless, the DBU rate already bundles infra, so **the v1 DBU-only
   cost model is essentially the *full* cost for 96% of this spend.** The
   council's "classic cloud-VM undercount" risk is real but empirically tiny
   and now *explicitly labelled per-row* rather than hidden (§3.2).
3. **The price join is clean.** 784,718 priced rows, **0** NULL list prices in
   the window — the silent-undercount risk did not materialise, but we still
   add a cheap NULL-price guard (§5.4).
4. **`system.lakeflow.pipelines` is populated and trustworthy** for DLT:
   146,050 rows / 57,188 distinct pipelines / **99.94%** have `created_by`.
   The §3.4 denormalisation (creator straight from the system table, no REST
   API) is safe. **But coverage is product-dependent** — 97% for DLT, 79% for
   SQL MVs, **0% for Vector Search** (those never get a `system.lakeflow`
   row). The "Snapshot missing" badge therefore must become *neutral and
   product-aware* — "metadata not available" is the *expected* state for some
   workloads, not an anomaly (§3.5).
5. **Double-counting with Instance Pools is small.** Only classic DLT
   ($1,334) can land on a pool; serverless cannot. Real but minor — disclosed,
   not corrected (§3.7).

**Net:** proceed, but build the honest, complete version (Option A below), not
the originally-specified DLT-only tab.

## 1. Goal

Today DBSpend360 has three top-level tabs — **Job Clusters**
(`dbspend360_total_job_spends`, keyed `cluster_id × job_id × run_id ×
usage_date`, `cluster_source = 'JOB'`), **All-Purpose Clusters**
(`dbspend360_total_all_purpose_spends`, keyed `cluster_id × user_id ×
usage_date`, `cluster_source IN ('UI','API')`), and **Instance Pools**
(`dbspend360_total_pool_spends`, keyed `instance_pool_id × cluster_id ×
usage_date`, `instance_pool_id IS NOT NULL`).

**None of them surface declarative / serverless pipeline-backed compute** —
Lakeflow Declarative Pipelines (DLT), DBSQL materialized views & streaming
tables, online tables / Lakebase, vector-search index sync, model-serving
pipelines, and AI-function batch jobs. This compute is *explicitly excluded*
from the Job and All-Purpose tabs (`cluster_source = 'PIPELINE'` is filtered
out, and serverless has no `cluster_source` at all), and per §0 it is **~$100K
/ 30 days** in the dev workspace alone — money the workspace owner currently
cannot see anywhere in the app.

All of it shares one billing key: `usage_metadata.dlt_pipeline_id`. The
pipeline behind DLT/SQL-MV/online-table workloads is described in
`system.lakeflow.pipelines` (name, creator, run-as, type).

Add a parallel **Pipeline Compute** experience as a **fourth top-level tab**,
shaped like the existing three but scoped to *all* `dlt_pipeline_id` DBU
consumption, **dimensioned by workload type** so the owner sees what each
dollar actually is. The tab has a single view (no sub-tabs):

- **By Pipeline** — one row per pipeline in the window, with a workload-type
  badge and a single drill-down: expand a pipeline row to see per-day cost.
  Powers "which pipelines are spending, of what type, and on which days".

After this change the navigation looks like:

```
Header (DBSpend360 + ThemeToggle)
├─ Tab: Job Clusters         (untouched)
├─ Tab: All-Purpose Clusters (untouched)
├─ Tab: Instance Pools       (untouched)
└─ Tab: Pipeline Compute     (new — single By-Pipeline view, workload-typed, per-day drill-down)
```

## 1.5. Confirmed decisions

The architectural forks below are **locked in** after the §0 materiality pass
and the workspace-owner review. They revise several decisions from the original
"DLT-only" MCQ pass; the superseded choices are retained in §3 as a historical
record.

| Fork | Decision | Detail in |
|---|---|---|
| Scope | **Broad — all `dlt_pipeline_id` spend, dimensioned by workload type.** Reverses the earlier "DLT-only" framing. `billing_origin_product` is a *first-class dimension* (column + KPI split + filter), not just a descriptive field, because DLT is only 25% of the spend. | §0, §3.1 |
| Grain | **Rollup: per-pipeline per-day per-product** `(workspace_id, pipeline_id, usage_date, billing_origin_product)` — keeping `billing_origin_product` in the grain makes the per-workload `$` split **exact** (it reconciles row-for-row with §0; no within-day "dominant product" approximation that would misattribute minority spend). **Staging: per-pipeline per-day per-cluster per-product** `(workspace_id, pipeline_id, usage_date, cluster_id, billing_origin_product)` so v2 cloud-cost can join on `cluster_id` with **no re-ingest**. The By-Pipeline read collapses product+day → pipeline; the single row expansion sums product within a day → per-day rows. **Both MERGEs match `cluster_id` null-safe** (serverless ⇒ `cluster_id = NULL`). | §3.3 |
| Filter | **`usage_metadata.dlt_pipeline_id IS NOT NULL`** as the sole row filter — captures BOTH serverless (`cluster_id` NULL) and classic. `billing_origin_product` is carried for *dimensioning/labelling*, never used to *drop* rows. | §3.1 |
| Cost model | **DBU list price only in v1, with explicit per-row honesty.** A derived `cost_basis` flag (`full` for serverless / `dbu_only` for classic / `partial` for mixed) tells the UI exactly which numbers exclude cloud VM. Cloud VM cost deferred to v2 (only matters for the ~4% classic). | §3.2 |
| Pricing | **List price (`pricing['default']`).** Stated in the UI footnote as list, not the invoiced/discounted rate. (Pre-existing app-wide behaviour; called out for honesty.) | §3.2 |
| Workload labelling | **Map `billing_origin_product` → friendly `workload_type`** (DLT / DBSQL Materialized View / Online Table / Vector Search / Model Serving / AI Functions / Other). Unknown/new products fall back to the raw value. | §3.1 |
| Owner attribution | **Surface `created_by` + `run_as`** from `system.lakeflow.pipelines`, denormalised. 99.94% populated for DLT (§0). Falls back to "Unknown" where metadata is absent (Vector Search etc.). | §3.4 |
| Update / maintenance | **Kept separable in staging now** (`update_cost` / `maintenance_cost` columns) per the council; rolled into one `databricks_cost` for the v1 UI total. Surfacing the split is a near-free v2 UI follow-up. | §3.6 |
| Snapshot/metadata state | **Three states, product-aware and neutral.** Active (no badge) / Deleted (yellow) / **"Metadata not available"** (neutral grey, NOT alarming) when no `system.lakeflow.pipelines` row. Vector Search is *expected* to have no row, so it is excluded from any "orphaned" KPI. | §3.5 |
| Cloud-cost source | **None in v1.** Schema reserves `cloud_cost DOUBLE` (always NULL in v1); staging keeps `cluster_id` so v2 needs no migration. | §3.2 |
| AI analysis | **One `analyze_pipeline_costs` LLM method**, fed `workload_type` + `cost_basis` context so it never gives confidently-wrong advice on incomplete numbers. No per-product prompt branching (bug-surface control). Endpoint `/api/pipelines/{id}/analyze`. | §4.1 |
| Sub-tabs | **None.** Single By-Pipeline view, row-expansion → per-day. | §3.3 |
| Navigation | **New top-level tab** (4th). | §4.2 |
| PR slicing | Single PR on `feat/pipeline-compute-tab`, sequential checkpoints (§8). Mirrors `plan_instance_pools_tab.md`. | §7, §8 |

## 2. Non-goals

- **No changes to existing tab behavior.** Job Clusters, All-Purpose, and
  Instance Pools render byte-identical output; their routers/components are
  untouched.
- **No changes to `dbspend360_cloud_cost_explorer`** or the
  `{aws,azure,gcp}_cloud_cost_explorer_app` notebooks. v1 ships without cloud
  VM cost for classic pipelines (the ~4%).
- **No changes to existing DDL tables.** Data lands in two new Delta tables.
  No backfill, no migration.
- **No per-table cost attribution.** Billing is at the pipeline/update level;
  per-table DBU is not natively extractable. Out of scope (§13).
- **No per-update drill-down in v1.** Pipeline-day is the finest grain
  surfaced. Per-update (`dlt_update_id`) is a v2 follow-up (§13).
- **No de-duplication of cross-tab overlap** (DLT-on-pool). Disclosed, not
  corrected (§3.7).
- **No alerts / budgets / scheduled reports** in this PR.

## 3. Key data-model decisions

### 3.1 What counts as "Pipeline Compute" spend? (scope + workload dimension)

DLT/declarative usage in `system.billing.usage` is identifiable via the
`usage_metadata` struct:

- **`dlt_pipeline_id IS NOT NULL`** — the authoritative, stable field.
  Populated for the entire declarative-pipeline family (DLT, DBSQL MVs/streaming
  tables, online tables, vector search, model serving, AI functions). This is
  the canonical filter.
- `dlt_update_id` / `dlt_maintenance_id` — sub-identifiers, NULL when
  `dlt_pipeline_id` is NULL; populated for update vs maintenance work.
- `cluster_id` — **NULL for serverless**, populated for classic. `job_id` /
  `job_run_id` are **expected NULL** for `dlt_pipeline_id` rows (asserted, not
  yet measured in §0 — confirmed by the CP2 exit check below; if non-NULL rows
  exist they signal cross-tab overlap with Job Clusters and §3.7 must be
  revised).
- `billing_origin_product` — **the workload-type dimension**: `DLT`, `SQL`,
  `DATABASE`, `VECTOR_SEARCH`, `MODEL_SERVING`, `AI_FUNCTIONS`, …

**Decision (confirmed): filter on `dlt_pipeline_id IS NOT NULL` and
*dimension* on `billing_origin_product`.**

**Why broad, not DLT-only?** §0 proved DLT is only 25% of the spend; DBSQL
MVs alone are 62%. A DLT-only tab would hide $75K/30d of pipeline-backed
compute that appears in no other tab. A broad-but-mislabelled tab ("DLT
Pipelines" showing $100K) would be dishonest. The resolution is breadth **with
an explicit workload dimension** so every dollar is correctly attributed.

**Why not use `billing_origin_product` as the *filter*?** Because that would
drop spend (the original §3.1 concern still holds — the enum evolves, new
products would silently vanish). Instead it is a *non-filtering dimension*:
new/unknown products still appear (under their raw value or "Other"), so
nothing is ever hidden.

**`workload_type` mapping** (friendly label, denormalised onto the rollup):

| `billing_origin_product` | `workload_type` |
|---|---|
| `DLT` | `DLT Pipeline` |
| `SQL` | `DBSQL Materialized View` |
| `DATABASE` | `Online Table` |
| `VECTOR_SEARCH` | `Vector Search` |
| `MODEL_SERVING` | `Model Serving` |
| `AI_FUNCTIONS` | `AI Functions` |
| anything else | the raw value (never dropped) |

`billing_origin_product` is kept in the rollup grain (§3.3), so every
product's dollars stay separately attributed — the per-workload `$` split is
exact, never folded into a single "dominant product" per day. The
**pipeline-level badge** (one label per pipeline row in the table) is the
cost-dominant `workload_type` across the window, computed as
`max_by(workload_type, struct(wl_cost, workload_type))` over a **per-workload
`SUM(total_cost)` sub-aggregate** (§5.1) — *not* `max_by(..., total_cost)` over
raw rows, which would pick the single largest row's product rather than the
workload with the largest summed cost. The `struct(..., workload_type)` second
arg makes the tiebreak deterministic (alphabetical) on equal cost. The badge is
display only; it never moves a dollar.

Serverless vs classic remains **derivable** (`cluster_id IS NULL` ⇒
serverless) and is denormalised as `compute_mode`
(`serverless`/`classic`/`mixed`).

### 3.2 Cost model — DBU list price only in v1, with per-row honesty

**Decision (confirmed): v1 ships `databricks_cost` (DBU × list price) only,
and labels exactly what that number includes per row.**

§0 showed 96% of this spend is **serverless**, where the DBU rate already
bundles infrastructure — so for the overwhelming majority, the DBU number *is*
the full cost. Only the ~4% **classic** spend has a separate cloud-VM line
that v1 omits.

Rather than a blanket "cost may be incomplete" disclaimer (which would
under-sell the 96% that is exact), the tab carries a derived **`cost_basis`**
flag per pipeline-day:

| `cost_basis` | When | UI |
|---|---|---|
| `full` | all rows serverless | no caveat — this is the complete cost |
| `dbu_only` | all rows classic | tiny info icon on `$`: *"Databricks DBU only — excludes cloud VM cost"* |
| `partial` | mixed serverless + classic | tiny info icon: *"Partly DBU-only — classic portion excludes cloud VM"* |

The summary strip states the split in plain numbers, e.g. *"96% of shown spend
is serverless (full cost); 4% is classic (DBU only — excludes cloud VM)."* When
a non-zero `mixed_spend` exists (§5.3), it is shown as a third figure so the
three percentages sum to 100% rather than implying serverless + classic is
exhaustive.

**Pricing honesty.** Costs use `pricing['default']` (list price), consistent
with every other tab. The tab footnote states: *"Costs are Databricks
list-price DBU; they exclude account-level discounts (list ≠ your invoice)."*
Matching the customer's negotiated rate is a pre-existing, app-wide gap, out of
scope here but disclosed.

**Schema reservation.** The rollup includes `cloud_cost DOUBLE` (**always NULL
in v1**) and `total_cost DOUBLE` (`= databricks_cost` in v1;
`databricks_cost + COALESCE(cloud_cost,0)` in v2). Staging keeps `cluster_id`,
so v2 cloud-cost join needs no re-ingest. The TS interface keeps
`cloud_cost?: number | null`; the column is hidden while every value is NULL.

### 3.3 Grain — staging keeps `cluster_id`, rollup is per-pipeline per-day per-product

**Decision (confirmed):**

```
Staging  PRIMARY KEY (workspace_id, pipeline_id, usage_date, cluster_id, billing_origin_product)
Rollup   PRIMARY KEY (workspace_id, pipeline_id, usage_date, billing_origin_product)
```

`workspace_id` is in the key because **`pipeline_id` is only unique within a
single workspace**. Staging additionally keeps `cluster_id` (NULL for
serverless) so the v2 cloud-cost join (which is `cluster_id`-keyed, like the
Job Clusters tab) requires **no re-ingest** — this kills the "false
zero-migration" defect the council flagged. The rollup aggregates `cluster_id`
away into `compute_mode` but **keeps `billing_origin_product` in the grain** so
the per-workload `$` split is exact and reconciles row-for-row with §0 (no
within-day dominant-product approximation that would misattribute minority
spend — see §3.1).

**Null-safe MERGE (correctness-critical).** Serverless rows carry
`cluster_id = NULL` — that is the serverless signal, so unlike the pool
collector (which coalesces NULL to a `'__pool_overhead__'` sentinel) we must
keep it NULL. Therefore **both MERGEs match `cluster_id` with null-safe
equality** (`t.cluster_id <=> s.cluster_id`, DataFrame `eqNullSafe`). A plain
`=` evaluates `NULL = NULL` as false, so every serverless pipeline-day — **96%
of the spend (§0)** — would miss the MERGE match and be **re-inserted on each
overlapping incremental run** (`get_date_window(..., overlap_days)`
reprocesses the trailing days), silently double-counting the majority of the
table. The rollup key has no nullable column, so its MERGE is unaffected.

The single By-Pipeline view supports **one level of expansion**: pipeline row →
per-day rows. The rollup's product grain is internal — the read sums products
within a day (§5.2), so the UI still shows exactly one row per pipeline-day.
Per-update drill-down is intentionally NOT in v1 (§3.6, §13).

### 3.4 Owner attribution — `created_by` + `run_as`, denormalized

**Decision (confirmed): surface `created_by` and `run_as`** from
`system.lakeflow.pipelines`, denormalised onto the rollup, shown in both list
and modal. §0 verified 99.94% of DLT pipelines have a human-readable
`created_by` — no GUID resolution, no REST API (the key simplification vs the
Instance Pools tab).

Both are SCD-collapsed (most-recent snapshot per `(workspace_id,
pipeline_id)`). When the snapshot is absent (§3.5) — common for Vector Search,
some SQL MVs — both fall back to NULL and the UI renders "Unknown". Cost is
never affected.

### 3.5 Metadata/snapshot state — three states, neutral and product-aware

`system.lakeflow.pipelines` is SCD2 (Public Preview, **Regional**) with
`change_time` and `delete_time`, giving three states. §0 showed snapshot
coverage is **product-dependent** (97% DLT, 79% SQL, **0% Vector Search**), so
the absence of a snapshot is the *expected* state for some workloads — the
badge must be neutral, not alarming.

| State | `metadata_missing` | `pipeline_deleted_at` | UI badge | When |
|---|---|---|---|---|
| Active | `false` | `NULL` | none | Snapshot row exists, `delete_time IS NULL`. |
| Deleted (visible) | `false` | TIMESTAMP | yellow "Deleted YYYY-MM-DD" | Deleted but SCD snapshot still in retention. |
| Metadata not available | `true` | `NULL` | **neutral grey "Metadata not available"** | No `system.lakeflow.pipelines` row — normal for Vector Search / cross-region / retention edge. |

**Per-field fallback when `metadata_missing = true`:** `pipeline_name` →
`'Pipeline {pipeline_id}'`; `created_by`/`run_as`/`pipeline_type` → NULL ("Unknown").

**KPI rule:** the summary's "metadata unavailable" count **excludes workloads
that never carry metadata** (e.g. Vector Search) — it only flags DLT/SQL
pipelines that *should* have a row but don't, so the number stays meaningful.

### 3.6 Update vs maintenance — separable in staging, aggregated in UI

A pipeline incurs DBU from **updates** (`dlt_update_id`) and **maintenance**
(`dlt_maintenance_id`, e.g. managed OPTIMIZE/VACUUM).

**Decision (confirmed): staging computes `update_cost` and `maintenance_cost`
separately now** (council fix — nearly free since we already read both IDs),
but the v1 UI shows one combined `databricks_cost`. Surfacing the split (and a
"maintenance ratio" KPI) becomes a pure UI/query v2 follow-up with **no
re-ingest** (§13). Note `update_cost + maintenance_cost` need **not** equal
`databricks_cost`: a row can carry neither sub-id (general/startup DBU), so the
two split columns are a lower bound, not a partition — the v1 total always uses
`databricks_cost`, never the sum of the splits. The rollup grain is
`(workspace_id, pipeline_id, usage_date, billing_origin_product)` (§3.3).

### 3.7 Overlap with other tabs

Disjoint from Job Clusters / All-Purpose by construction (those filter
`cluster_source = 'JOB'` / `IN ('UI','API')`; declarative classic clusters are
expected to be `'PIPELINE'` and serverless has none; `job_id`/`job_run_id`
expected NULL). **This disjointness is an assumption inherited from the tab
filters, not measured in §0 — the CP2 exit check below confirms both
`job_id`/`job_run_id` are NULL and no classic pipeline cluster carries a
`JOB`/`UI`/`API` `cluster_source`; if either fails, this section's overlap
bound is wrong and must be widened before merge.**

**Can overlap with Instance Pools:** a *classic* pipeline on an instance pool
appears in both `dbspend360_total_pool_spends` and the new rollup. §0 bounds
this at the classic share (~$3.7K/30d, mostly Model Serving + classic DLT) —
real but minor. Disclosed in the README and a tab footnote ("Classic pipelines
on instance pools may also appear under Instance Pools"), not de-duplicated.

## 4. New + changed surface area

### 4.1 New files

**Pipeline (Databricks notebooks).** Sibling notebooks; existing pipelines
untouched.

- `jobs/ddls/dbspend360_pipeline_dbu_cost.ipynb` — DDL for the staging table.
  Keyed `(workspace_id, pipeline_id, usage_date, cluster_id,
  billing_origin_product)`. Columns:
  `workspace_id`, `pipeline_id`, `usage_date`, `cluster_id`,
  `databricks_cost`, `update_cost`, `maintenance_cost`, `compute_mode`
  (row-level `serverless`/`classic`), `billing_origin_product`, `currency`,
  `sku_name`, `created_at`, `updated_at`.
- `jobs/ddls/dbspend360_total_pipeline_spends.ipynb` — DDL for the
  denormalized rollup. Keyed `(workspace_id, pipeline_id, usage_date,
  billing_origin_product)`; adds `workload_type`, `compute_mode`
  (`serverless`/`classic`/`mixed`),
  `cost_basis` (`full`/`dbu_only`/`partial`), pipeline metadata
  (`pipeline_name`, `pipeline_type`, `created_by`, `run_as`), state flags
  (`metadata_missing BOOLEAN`, `pipeline_deleted_at TIMESTAMP`), reserved
  `cloud_cost DOUBLE` (always NULL v1), `total_cost DOUBLE`.
- `jobs/notebooks/dbspend360_pipeline_dbu_cost_app.ipynb` — DBU collection app
  (sibling of `dbspend360_pool_dbu_cost_app.ipynb`). Reuses
  `utils_common.ipynb`. Filters `system.billing.usage` to
  `usage_metadata.dlt_pipeline_id IS NOT NULL`, **inner-joins** (with a
  NULL-price guard) `system.billing.list_prices`, derives row-level
  `compute_mode`, splits `update_cost`/`maintenance_cost`, carries
  `cluster_id` + `billing_origin_product`. SQL per §5.4.
- `jobs/notebooks/pipeline_spends_app.ipynb` — final rollup app (sibling of
  `pool_spends_app.ipynb`). Aggregates staging to pipeline-day, derives
  `compute_mode`/`cost_basis`/`workload_type`, SCD-collapses
  `system.lakeflow.pipelines` and denormalizes `name`, `pipeline_type`,
  `created_by`, `run_as`, `delete_time` → `pipeline_deleted_at`. **No
  cloud-cost join in v1** (`cloud_cost = CAST(NULL AS DOUBLE)`). SQL per §5.5.

**Backend (FastAPI):**

- `server/routers/pipelines.py` — new router under `/api/pipelines/*`
  (endpoints in §6).
- (No new model file; new Pydantic models live alongside existing ones in
  `server/models/job_spend.py`.)

**LLM service:**

- (No new file.) New `analyze_pipeline_costs()` method and
  `PIPELINE_ANALYSIS_PROMPT` constant in `server/services/llm_service.py`,
  fed `workload_type` + `cost_basis` so advice is scoped to the number's
  trustworthiness.

**Frontend (React):**

- `client/src/types/pipeline.ts` — TS interfaces: `PipelineDailySpend`,
  `GroupedPipeline` (with `days: PipelineDailySpend[]`),
  `PipelineSummaryMetrics`, `PipelineDetails`, `PipelineAnalysis`, paginated
  wrappers.
- `client/src/hooks/usePipelines.ts` — `usePipelines`, `usePipelineSummary`,
  `useTopPipelines`, `usePipelineDetails`, `usePipelineAnalysis`. Same React
  Query / `keepPreviousData` / prefetch pattern as `useInstancePools.ts`.
- `client/src/components/PipelineDashboard.tsx` — single view (no inner `<Tabs>`).
- `client/src/components/PipelineSummaryCards.tsx` — KPI strip: total DBU
  spend, **workload-type breakdown** (DLT vs SQL-MV vs Online Table vs …),
  distinct pipeline count, **serverless/classic/mixed cost split with the
  full-vs-DBU-only footnote** (three buckets summing to total — §5.3),
  top-cost pipeline, count of DLT/SQL pipelines with `metadata_missing = true`
  (Vector Search excluded).
- `client/src/components/PipelinesTable.tsx` — By-Pipeline table: `pipeline_id`,
  `pipeline_name` (with the §3.5 neutral state badge), **`workload_type`
  badge**, `compute_mode` badge, **`cost_basis` info-icon on the `$`**,
  `created_by`, `active_days`, `databricks_cost`, `total_cost`. Single-level
  row expansion → per-day. Pipeline name clickable → details modal.
- `client/src/components/PipelineFilterControls.tsx` — date presets + **workload-type
  filter chips** + search by name / id / creator.
- `client/src/components/PipelineDetailsModal.tsx` — config
  (`workload_type`, `pipeline_type`, `created_by`, `run_as`, `compute_mode`,
  `cost_basis`, tags) + LLM analysis from `/api/pipelines/{id}/analyze`.
  Renders the §3.5 state banner and the cost-basis caveat.

### 4.2 Changed files

- `jobs/ddls/create_all_tables.ipynb` — add the two new DDL notebook names to
  `DDL_NOTEBOOKS`.
- `jobs/resource_templates/DBSPEND360.yaml` — add two task entries
  (`Dbspend360_pipeline_dbu_costs`, `pipeline_spends`). The first has **no
  upstream dependency in v1** — it reads `system.billing.usage` directly and
  never touches cloud cost, so coupling it to `cloud_cost_explorer` now would
  needlessly make v1 pipeline freshness fail whenever that unrelated task does.
  The `cloud_cost_explorer` edge is added in v2, when the rollup actually
  starts reading that table. The second depends on the first. New branch runs
  in parallel with the existing three. Use the workspace path root from
  `.cursor/rules/deployment-paths.mdc`:
  `/Workspace/Users/aditya.mandiwal@databricks.com/deployed from cursor/jobs/notebooks/<name>`.
- `server/models/job_spend.py` — append 6 models: `PipelineDailySpend`,
  `GroupedPipeline` (with `days: list[PipelineDailySpend]`),
  `PipelineSummaryMetrics`, `PipelineDetails`, `PipelineAnalysis`,
  `PaginatedPipelines`. No edits to existing models.
- `server/services/databricks_service.py` — add ~6 async methods. In
  `__init__`, add `self.pipeline_table_name = app_config.pipeline_table_name`.
  Methods: `get_pipelines_grouped`, `get_pipeline_summary_metrics`,
  `get_top_pipelines`, `get_pipeline_details`, `_get_batch_pipeline_days`,
  `get_pipeline_cost_summary`. **No metadata cache / REST API.**
- `server/services/llm_service.py` — append `PIPELINE_ANALYSIS_PROMPT` and
  `analyze_pipeline_costs`. Built on `CLUSTER_ANALYSIS_SYSTEM_PROMPT`'s shape
  with declarative-pipeline guidance + **mandatory cost-basis caveat**
  (the prompt is told when the number is DBU-only). No per-product branching.
- `server/app.py` — `from server.routers.pipelines import router as
  pipelines_router` + one `app.include_router(...)` **before** the
  `StaticFiles` mount.
- `server/config/config_loader.py` — add `pipeline_table_name` property
  (mirrors `pool_table_name`) + add to `to_dict()`'s `databricks` block.
- `config/app.dev.config` — add `pipeline_table_name =
  dbspend360.04june.dbspend360_total_pipeline_spends`.
- `client/src/lib/api-client.ts` — extend `ApiClient` with `getPipelines`,
  `getPipelineSummary`, `getTopPipelines`, `getPipelineDetails`,
  `getPipelineAnalysis`.
- `client/src/components/Dashboard.tsx` — extend `VALID_TABS` with
  `'pipelines'`, add a 4th `<TabsTrigger value="pipelines">Pipeline
  Compute</TabsTrigger>` and `<TabsContent value="pipelines"><PipelineDashboard
  /></TabsContent>`. The `?tab=...` URL machinery is reused verbatim.
- `client/src/fastapi_client/` — regenerated by
  `scripts/make_fastapi_client.py`. No hand edits.

### 4.3 Untouched but reused

- `jobs/notebooks/{aws,azure,gcp}_cloud_cost_explorer_app.ipynb` — not touched
  in v1 (DBU-only).
- `jobs/notebooks/utils_common.ipynb` — `get_date_window`, `log_audit_run`,
  `validate_*`, `safe_cache`, `build_table_fqn` reused unchanged.
- `client/src/components/ui/tabs.tsx` — adding a 4th tab is additive.

## 5. Sample SQL for the new endpoints

### 5.1 `get_pipelines_grouped()`

One row per pipeline in the window. Metadata is denormalized, so no live join.
**`compute_mode` / `workload_type` / `cost_basis` are pre-computed in the
rollup** (the rollup is the only place they're derived), so the read collapses
them deterministically — `MAX(...)` for constant-per-pipeline metadata, a
**per-workload `SUM` sub-aggregate (`wl`) feeding `max_by`** for the
cost-dominant badge, and explicit `MIN/MAX`/`COUNT(DISTINCT)` CASEs for
`compute_mode`/`cost_basis` — never the non-deterministic `ANY_VALUE` the
council flagged.

```sql
WITH filtered AS (
    SELECT *
    FROM {pipeline_table_name}
    WHERE usage_date >= '{start_date}'
      AND usage_date <= '{end_date}'
      {workload_filter}              -- optional: AND workload_type IN (...)
),
wl AS (   -- per-pipeline per-workload summed cost: the basis for the
          -- cost-DOMINANT badge. Summing first is what makes the label the
          -- workload with the largest TOTAL cost, not the product on the
          -- single largest row (which max_by over raw rows would pick).
    SELECT workspace_id, pipeline_id, workload_type,
           SUM(total_cost) AS wl_cost
    FROM filtered
    GROUP BY workspace_id, pipeline_id, workload_type
),
wl_dominant AS (
    SELECT workspace_id, pipeline_id,
           -- struct(wl_cost, workload_type): cost is the primary sort key,
           -- workload_type breaks ties alphabetically so the label is
           -- deterministic on equal cost.
           max_by(workload_type, struct(wl_cost, workload_type)) AS workload_type
    FROM wl
    GROUP BY workspace_id, pipeline_id
),
pipeline_level AS (
    SELECT workspace_id,
           pipeline_id,
           MAX(pipeline_name)             AS pipeline_name,
           MAX(pipeline_type)             AS pipeline_type,
           MAX(created_by)                AS created_by,
           MAX(run_as)                    AS run_as,
           -- compute_mode is constant per (pipeline,day,product) but can vary
           -- across days/products; collapse to a pipeline-level label
           -- deterministically.
           CASE
             WHEN COUNT(DISTINCT compute_mode) > 1 THEN 'mixed'
             ELSE MAX(compute_mode)
           END                            AS compute_mode,
           CASE
             WHEN MIN(cost_basis) = MAX(cost_basis) THEN MAX(cost_basis)
             ELSE 'partial'
           END                            AS cost_basis,
           BOOL_OR(metadata_missing)      AS metadata_missing,
           MAX(pipeline_deleted_at)       AS pipeline_deleted_at,
           COUNT(DISTINCT usage_date)     AS active_days,
           SUM(databricks_cost)           AS total_databricks_cost,
           SUM(total_cost)                AS total_cost
    FROM filtered
    GROUP BY workspace_id, pipeline_id
)
SELECT pl.*, wd.workload_type, COUNT(*) OVER() AS total_matching
FROM pipeline_level pl
JOIN wl_dominant wd USING (workspace_id, pipeline_id)
{search_clause}
ORDER BY total_cost DESC
LIMIT {limit} OFFSET {offset}
```

`{workload_filter}` applies the workload-type chip selection (default: none →
all). `{search_clause}` matches `pipeline_name` (case-insensitive substring),
`pipeline_id` (exact), or `created_by` (case-insensitive substring).

### 5.2 `_get_batch_pipeline_days()` — per-day expansion

```sql
SELECT workspace_id,
       pipeline_id,
       usage_date,
       SUM(databricks_cost)                        AS databricks_cost,
       -- collapse the per-product cost_basis to one label for the day
       CASE WHEN MIN(cost_basis) = MAX(cost_basis) THEN MAX(cost_basis)
            ELSE 'partial' END                     AS cost_basis,
       SUM(COALESCE(cloud_cost, 0))                AS cloud_cost,
       SUM(total_cost)                             AS total_cost
FROM {pipeline_table_name}
WHERE pipeline_id IN ({pipeline_id_list})
  AND usage_date >= '{start_date}' AND usage_date <= '{end_date}'
GROUP BY workspace_id, pipeline_id, usage_date
ORDER BY pipeline_id, usage_date
```

The rollup is at product grain (§3.3), so the per-day read sums across products
within each day before the service groups by pipeline into each
`GroupedPipeline.days` — the UI still sees exactly one row per pipeline-day.
The §9 invariant "sum of `days[].total_cost` equals the pipeline's
`total_cost`" is therefore structural.

### 5.3 `get_pipeline_summary_metrics()`

```sql
WITH filtered AS (
    SELECT * FROM {pipeline_table_name}
    WHERE usage_date >= '{start_date}' AND usage_date <= '{end_date}'
      {workload_filter}
),
wl AS (   -- per-pipeline per-workload summed cost (basis for cost-dominant
          -- label; see §5.1 — sum first, then max_by, never max_by over raw
          -- rows).
    SELECT workspace_id, pipeline_id, workload_type, SUM(total_cost) AS wl_cost
    FROM filtered GROUP BY workspace_id, pipeline_id, workload_type
),
pipe_wl AS (
    SELECT workspace_id, pipeline_id,
           max_by(workload_type, struct(wl_cost, workload_type)) AS workload_type
    FROM wl GROUP BY workspace_id, pipeline_id
),
pipe AS (   -- collapse to one row per pipeline first, so the mode/metadata
            -- counts are per-pipeline and sum to total_pipelines
    SELECT workspace_id, pipeline_id,
           CASE WHEN COUNT(DISTINCT compute_mode) > 1 THEN 'mixed'
                ELSE MAX(compute_mode) END AS compute_mode,
           BOOL_OR(metadata_missing)       AS metadata_missing,
           SUM(total_cost)                 AS pipe_cost,
           SUM(CASE WHEN compute_mode='serverless' THEN total_cost ELSE 0 END) AS serverless_cost,
           SUM(CASE WHEN compute_mode='classic'    THEN total_cost ELSE 0 END) AS classic_cost,
           -- 'mixed' = a (pipeline,day,product) straddling serverless+classic;
           -- its $ belongs to neither pure bucket, so track it explicitly so
           -- serverless_spend + classic_spend + mixed_spend == total_spend
           -- (the summary footnote must not imply the split is exhaustive of
           -- two buckets when a third exists).
           SUM(CASE WHEN compute_mode='mixed'      THEN total_cost ELSE 0 END) AS mixed_cost
    FROM filtered
    GROUP BY workspace_id, pipeline_id
)
SELECT
    COUNT(*)                                                 AS total_pipelines,
    SUM(CASE WHEN p.compute_mode='serverless' THEN 1 ELSE 0 END) AS serverless_pipelines,
    SUM(CASE WHEN p.compute_mode='classic'    THEN 1 ELSE 0 END) AS classic_pipelines,
    SUM(CASE WHEN p.compute_mode='mixed'      THEN 1 ELSE 0 END) AS mixed_pipelines,
    -- only count metadata-missing for workloads that SHOULD have a snapshot.
    -- The IN-list is the single METADATA_BEARING_WORKLOADS constant (defined
    -- next to WORKLOAD_MAP in §5.5 and reused by the backend), NOT a literal
    -- re-typed here — so adding a workload type updates both places at once.
    -- pw.workload_type is the cost-dominant label (sum-then-max_by), so a
    -- pipeline is judged metadata-bearing by its dominant workload, not an
    -- arbitrary largest row.
    SUM(CASE WHEN p.metadata_missing AND pw.workload_type IN ({metadata_bearing_workloads})
             THEN 1 ELSE 0 END)                             AS metadata_unavailable,
    SUM(p.pipe_cost)                                        AS total_spend,
    SUM(p.serverless_cost)                                  AS serverless_spend,   -- full cost
    SUM(p.classic_cost)                                     AS classic_spend,      -- DBU only
    SUM(p.mixed_cost)                                       AS mixed_spend         -- partial (classic portion DBU only)
FROM pipe p
JOIN pipe_wl pw USING (workspace_id, pipeline_id)
```

The serverless/classic split that sums to `total_pipelines` (mode-switching
pipelines land in `mixed`, never double-counted) fixes the council's
"COUNT(DISTINCT CASE) can exceed total" defect. The `$` split is reported as
**three** buckets — `serverless_spend` + `classic_spend` + `mixed_spend` ==
`total_spend` — so the summary footnote stays exact even when mixed rows exist
(it does not imply two buckets exhaust the total). A separate small query
returns the per-`workload_type` `$` breakdown for the KPI strip — and because
`billing_origin_product` is in the rollup grain (§3.3) it is just
`SELECT workload_type, SUM(total_cost) FROM filtered GROUP BY workload_type`,
which is **exact** (reconciles row-for-row with §0, no dominant-product
approximation).

### 5.4 Staging — DBU collection (`dbspend360_pipeline_dbu_cost_app`)

```python
# Any billing row with a non-null dlt_pipeline_id: captures BOTH serverless
# (cluster_id NULL) and classic, across ALL declarative products (§3.1).
usage_df = (
    spark.table("system.billing.usage").alias("usage")
        .filter(
            (F.col("usage.usage_date") >= F.lit(start_dt)) &
            (F.col("usage.usage_date") <= F.lit(end_dt)) &
            (F.col("usage.usage_metadata")["dlt_pipeline_id"].isNotNull())
        )
)
if self.workspace_ids is not None:
    usage_df = usage_df.filter(F.col("usage.workspace_id").isin(self.workspace_ids))

list_prices_df = spark.table("system.billing.list_prices").alias("list_prices")

# INNER join (council fix): a missing/renamed SKU must NOT silently vanish.
joined = usage_df.join(
    list_prices_df,
    on=(
        (F.col("usage.sku_name") == F.col("list_prices.sku_name")) &
        (F.col("usage.usage_start_time") >= F.col("list_prices.price_start_time")) &
        (
            (F.col("usage.usage_start_time") < F.col("list_prices.price_end_time")) |
            F.col("list_prices.price_end_time").isNull()
        )
    ),
    how="inner",
)

# Guard (two-directional): the inner price join must be exactly 1:1. A DROP
# (join_cnt < left_cnt) means a SKU had no list price (SKU drift) and its
# usage silently vanishes. A FAN-OUT (join_cnt > left_cnt) means a SKU matched
# >1 overlapping price row (overlapping validity windows / duplicate prices)
# and its cost is silently MULTIPLIED — checking only the drop direction (the
# original guard) would miss this and inflate the total. Assert equality.
#
# Cost note (deliberate): these two .count() actions add two scans of the
# filtered usage set purely for the 1:1 assertion (§0 observed 0 NULL prices,
# so it guards a near-non-event). Correctness-over-speed is the intended
# trade-off here; cache usage_df first if the scan cost ever matters.
usage_df = safe_cache(usage_df)
left_cnt = usage_df.count()
join_cnt = joined.select("usage.usage_start_time").count()
if join_cnt != left_cnt:
    direction = "DROP" if join_cnt < left_cnt else "FAN_OUT"
    log.warning(
        "PRICE_JOIN_%s: usage rows %d -> joined rows %d (delta %+d). "
        "Expected 1:1 (one list price per SKU/time). Investigate before "
        "trusting totals.", direction, left_cnt, join_cnt, join_cnt - left_cnt
    )

cluster_id = F.col("usage.usage_metadata")["cluster_id"]
with_cols = (
    joined
    .withColumn("cluster_id", cluster_id)
    .withColumn("compute_mode",
        F.when(cluster_id.isNull(), F.lit("serverless")).otherwise(F.lit("classic")))
    .withColumn("row_cost",
        F.col("usage.usage_quantity") * F.col("list_prices.pricing")["default"].cast("double"))
    .withColumn("is_update",
        F.col("usage.usage_metadata")["dlt_update_id"].isNotNull())
    .withColumn("is_maint",
        F.col("usage.usage_metadata")["dlt_maintenance_id"].isNotNull())
)

agg_df = (
    with_cols.groupBy(
        F.col("usage.workspace_id").alias("workspace_id"),
        F.col("usage.usage_metadata")["dlt_pipeline_id"].alias("pipeline_id"),
        F.col("usage.usage_date").alias("usage_date"),
        F.col("cluster_id"),                                  # staging keeps cluster_id (§3.3)
        F.col("usage.billing_origin_product").alias("billing_origin_product"),
        F.col("compute_mode"),
    ).agg(
        F.sum("row_cost").alias("databricks_cost"),
        F.sum(F.when(F.col("is_update"), F.col("row_cost"))).alias("update_cost"),
        F.sum(F.when(F.col("is_maint"),  F.col("row_cost"))).alias("maintenance_cost"),
        F.concat_ws(" + ",
            F.array_sort(F.collect_set(F.col("usage.sku_name")))).alias("sku_name"),
    )
    .withColumn("currency", F.lit("USD"))
)
```

MERGE key: `(workspace_id, pipeline_id, usage_date, cluster_id,
billing_origin_product)`. **The MERGE condition matches `cluster_id` with
null-safe equality** (`t.cluster_id <=> s.cluster_id`), because serverless rows
carry `cluster_id = NULL`; a plain `=` never matches NULLs and would re-insert
~96% of the spend on every overlapping incremental run (§3.3). The other key
columns are non-nullable and use `=`.

### 5.5 Rollup — derive dimensions + metadata denormalization (`pipeline_spends_app`)

```python
WORKLOAD_MAP = {
    "DLT": "DLT Pipeline", "SQL": "DBSQL Materialized View",
    "DATABASE": "Online Table", "VECTOR_SEARCH": "Vector Search",
    "MODEL_SERVING": "Model Serving", "AI_FUNCTIONS": "AI Functions",
}
# Single source of truth for "which workloads are expected to carry a
# system.lakeflow.pipelines snapshot" — reused by the §5.3 metadata-missing
# KPI so the two never drift. Vector Search etc. are excluded by design.
METADATA_BEARING_WORKLOADS = {
    "DLT Pipeline", "DBSQL Materialized View", "Online Table",
}

# 1) collapse staging (per cluster) to pipeline-day-PRODUCT, deriving the
#    three dimensions. billing_origin_product STAYS in the grain (§3.3) so the
#    per-workload $ split is exact — no within-day dominant-product collapse.
staging = spark.table(self.source_table)  # dbspend360_pipeline_dbu_cost
day = (
    staging.groupBy("workspace_id", "pipeline_id", "usage_date",
                    "billing_origin_product")
    .agg(
        F.sum("databricks_cost").alias("databricks_cost"),
        F.sum("update_cost").alias("update_cost"),
        F.sum("maintenance_cost").alias("maintenance_cost"),
        # a single (pipeline, day, product) can still straddle serverless +
        # classic clusters → collapse to 'mixed'.
        F.when(F.countDistinct("compute_mode") > 1, F.lit("mixed"))
         .otherwise(F.first("compute_mode")).alias("compute_mode"),
        F.concat_ws(" + ", F.array_sort(F.collect_set("sku_name"))).alias("sku_name"),
        F.first("currency").alias("currency"),
    )
    .withColumn("cost_basis",
        F.when(F.col("compute_mode") == "serverless", F.lit("full"))
         .when(F.col("compute_mode") == "classic",    F.lit("dbu_only"))
         .otherwise(F.lit("partial")))
)
mapping = F.create_map([F.lit(x) for kv in WORKLOAD_MAP.items() for x in kv])
day = day.withColumn("workload_type",
    F.coalesce(mapping[F.col("billing_origin_product")], F.col("billing_origin_product")))

# 2) SCD-collapse system.lakeflow.pipelines (most-recent per workspace+pipeline).
pipelines_df = spark.sql("""
    SELECT workspace_id, pipeline_id,
           name AS pipeline_name, pipeline_type, created_by, run_as,
           delete_time AS pipeline_deleted_at
    FROM system.lakeflow.pipelines
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY workspace_id, pipeline_id ORDER BY change_time DESC) = 1
""")

joined = (
    day.alias("d")
    .join(pipelines_df.alias("p"),
          on=((F.col("d.workspace_id") == F.col("p.workspace_id")) &
              (F.col("d.pipeline_id")  == F.col("p.pipeline_id"))),
          how="left")
    .withColumn("metadata_missing", F.col("p.pipeline_name").isNull())
    .withColumn("pipeline_name",
        F.coalesce(F.col("p.pipeline_name"),
                   F.concat(F.lit("Pipeline "), F.col("d.pipeline_id"))))
    .withColumn("pipeline_deleted_at", F.col("p.pipeline_deleted_at"))
    .withColumn("cloud_cost", F.lit(None).cast("double"))   # v1 reserved
    .withColumn("total_cost",
        F.coalesce(F.col("d.databricks_cost"), F.lit(0.0)) +
        F.coalesce(F.col("cloud_cost"),         F.lit(0.0)))
)
```

MERGE key: `(workspace_id, pipeline_id, usage_date, billing_origin_product)`
(all non-nullable, so plain `=` is safe here — the null-safe concern is
staging-only, §5.4).

> Note: unlike the Instance Pools rollup, **no REST API and no
> `pipeline_metadata_cache`** are needed — `created_by`/`run_as` come straight
> from the system table (§3.4, verified 99.94% populated in §0).

## 6. New backend endpoints

All under `/api/pipelines/`, mirroring `instance_pools_router`.

| Method | Path | Response | Mirrors |
|---|---|---|---|
| GET | `/summary` | `PipelineSummaryMetrics` | `/api/instance-pools/summary` |
| GET | `/grouped` | `PaginatedPipelines` | `/api/instance-pools/grouped` |
| GET | `/top-pipelines` | `list[GroupedPipeline]` | `/api/instance-pools/top-pools` |
| GET | `/{id}/details` | `PipelineDetails` | `/api/instance-pools/{id}/details` |
| GET | `/{id}/analyze` | `PipelineAnalysis` | `/api/instance-pools/{id}/analyze` |
| GET | `/health` | `{status, service}` | `/api/instance-pools/health` |

All paginated/filtered endpoints accept `start_date` / `end_date` / `page` /
`per_page` / `search`, plus an optional `workload_type` multi-value filter.
`_validate_date_range` is duplicated from `instance_pools.py` (one-function
duplication preferred over a shared module).

**`pipeline_id` is only unique within a workspace (§3.3), so the two id-keyed
endpoints (`/{id}/details`, `/{id}/analyze`) accept an optional
`workspace_id` query param.** When omitted, the service resolves across
workspaces and, if `>1` workspace carries that `pipeline_id`, returns HTTP 409
naming the candidates rather than silently picking one — so the single-workspace
dev path stays zero-friction while multi-workspace deployments cannot return a
wrong-workspace pipeline. The service methods (`get_pipeline_details`,
`get_pipeline_cost_summary`) take `pipeline_id` **and** optional `workspace_id`,
and scope the `system.lakeflow.pipelines` QUALIFY + rollup reads by both when
`workspace_id` is supplied.

## 7. Slicing strategy

**Single PR on `feat/pipeline-compute-tab`** — pipeline + backend + UI ship
together. Same reasoning as the Instance Pools plan: one review surface, no
intermediate "tab exists but shows zero rows" state on `main`. Internally
organized as the checkpoints in §8.

## 8. Implementation checkpoints

Conventions: **Read first**, **Create / modify**, **Implementation notes**,
**Exit criteria**. In order.

### CP1 — Provision the two new Delta tables

**Read first.** `jobs/ddls/dbspend360_pool_dbu_cost.ipynb`,
`jobs/ddls/dbspend360_total_pool_spends.ipynb`,
`jobs/ddls/create_all_tables.ipynb`.

**Create / modify.**
- `jobs/ddls/dbspend360_pipeline_dbu_cost.ipynb` (new) — staging schema per §4.1
  (includes `cluster_id`, `update_cost`, `maintenance_cost`,
  `billing_origin_product`).
- `jobs/ddls/dbspend360_total_pipeline_spends.ipynb` (new) — rollup schema per
  §4.1 (includes `workload_type`, `cost_basis`, `metadata_missing`, reserved
  `cloud_cost DOUBLE`).
- `jobs/ddls/create_all_tables.ipynb` — append both names to `DDL_NOTEBOOKS`.

**Implementation notes.** Mirror existing DDL style (widgets, `CLUSTER BY
AUTO`, `dbutils.notebook.exit` returning the FQN). Rollup columns:
`workspace_id STRING`, `pipeline_id STRING`, `usage_date DATE`,
`pipeline_name STRING`, `pipeline_type STRING`, `created_by STRING`,
`run_as STRING`, `workload_type STRING`, `compute_mode STRING`,
`cost_basis STRING`, `metadata_missing BOOLEAN`,
`pipeline_deleted_at TIMESTAMP`, `databricks_cost DOUBLE`,
`update_cost DOUBLE`, `maintenance_cost DOUBLE`, `cloud_cost DOUBLE`,
`total_cost DOUBLE`, `currency STRING`, `sku_name STRING`,
`billing_origin_product STRING`, `created_at TIMESTAMP`,
`updated_at TIMESTAMP`.

**Exit criteria.**
1. Both notebooks deploy; `create_all_tables` lists both as `SUCCESS`.
2. `DESCRIBE TABLE <catalog>.<schema>.dbspend360_total_pipeline_spends` shows
   the expected columns.
3. `DESCRIBE TABLE system.lakeflow.pipelines` confirms `pipeline_id`,
   `workspace_id`, `name`, `pipeline_type`, `created_by`, `run_as`, `tags`,
   `change_time`, `delete_time` (verified present in §0). If any name differs,
   update §5.5 before CP3.

### CP2 — Staging DBU collection pipeline

**Read first.** `jobs/notebooks/dbspend360_pool_dbu_cost_app.ipynb`,
`jobs/notebooks/utils_common.ipynb`, the CP1 staging DDL.

**Create.** `jobs/notebooks/dbspend360_pipeline_dbu_cost_app.ipynb`.

**Implementation notes.** Sibling of the pool collector with these deltas:
filter `usage_metadata.dlt_pipeline_id IS NOT NULL`; **inner** price join +
**two-directional** `PRICE_JOIN_*` guard (drop *and* fan-out); aggregation key
`(workspace_id, pipeline_id, usage_date, cluster_id, billing_origin_product)`;
row-level `compute_mode` from `cluster_id`; split
`update_cost`/`maintenance_cost`; `TABLE_NAME =
"dbspend360_pipeline_dbu_cost"`. **The MERGE matches `cluster_id` null-safe
(`<=>`/`eqNullSafe`)** — do NOT coalesce NULL to a sentinel (NULL is the
serverless signal); a plain `=` would re-insert serverless rows on every
overlapping run (§3.3/§5.4). SQL per §5.4.

**Exit criteria.**
1. Manual dev run for a 30-day window completes with non-zero
   `merged_row_count` (~2,370 pipelines expected per §0).
2. `SELECT compute_mode, COUNT(*) ... GROUP BY 1` shows serverless dominant
   (≈96% by cost per §0).
3. `SELECT billing_origin_product, ROUND(SUM(databricks_cost)) ... GROUP BY 1`
   roughly matches the §0 table (SQL > DLT > DATABASE > …).
4. `SELECT COUNT(*) WHERE pipeline_id IS NULL` = 0; no `PRICE_JOIN_DROP`/
   `PRICE_JOIN_FAN_OUT` warning in the log (or it is explained).
5. **Disjointness probe (§3.1/§3.7):** against `system.billing.usage` for the
   window with `usage_metadata.dlt_pipeline_id IS NOT NULL`, confirm
   `COUNT(*) WHERE usage_metadata.job_id IS NOT NULL OR
   usage_metadata.job_run_id IS NOT NULL` = 0. If non-zero, the Job/All-Purpose
   overlap claim in §3.7 is false — stop and revise §3.7 before CP3.
6. Audit log entry `SUCCESS`.

### CP3 — Rollup pipeline

**Read first.** `jobs/notebooks/pool_spends_app.ipynb`, output of CP2.

**Create.** `jobs/notebooks/pipeline_spends_app.ipynb`.

**Implementation notes.** Per §5.5: collapse staging to
pipeline-day-**product** (`billing_origin_product` stays in the grain — do NOT
collapse to a dominant product); derive `compute_mode`/`cost_basis`/
`workload_type` per product row; **drop the REST API / metadata cache**;
SCD-collapse `system.lakeflow.pipelines` on `(workspace_id, pipeline_id)`;
`metadata_missing = pipeline_name IS NULL` (before COALESCE fallback);
`cloud_cost = CAST(NULL AS DOUBLE)` with a `# TODO(v2)` marker. The rollup
MERGE key is `(workspace_id, pipeline_id, usage_date, billing_origin_product)`.

**Exit criteria.**
1. Manual dev run `SUCCESS`.
2. `SUM(databricks_cost)` of the rollup equals that of the CP2 staging table
   for the same window (cluster_id collapse is loss-free; product is retained
   in the grain). Re-run CP2's collector over an overlapping window and confirm
   the staging row count + `SUM` are unchanged (null-safe MERGE, §5.4).
3. `cost_basis` matches `compute_mode` (`full`↔serverless, `dbu_only`↔classic,
   `partial`↔mixed); never NULL.
4. `workload_type` distribution matches §0 (DLT ≈ 1,127 = 1,056 serverless +
   71 classic, SQL ≈ 636, …).
5. `metadata_missing` never NULL; ≈100% TRUE for Vector Search, ≈3% for DLT
   (per §0).
6. `SELECT SUM(cloud_cost)` returns NULL (v1 invariant).
7. `created_by` populated for active DLT pipelines.

### CP4 — DAB wiring

**Read first.** `jobs/resource_templates/DBSPEND360.yaml`.

**Modify.** Append `Dbspend360_pipeline_dbu_costs` (no upstream in v1 — see
§4.2) and `pipeline_spends` (depends on the first). Use the
`deployed from cursor/` workspace path root.

**Exit criteria.**
1. `databricks bundle validate` passes.
2. `databricks bundle deploy` updates the dev job.
3. A manual run completes with all downstream tasks `SUCCEEDED` (root + 2 each
   for job / all-purpose / pool / pipeline).

### CP5 — Backend models + config

**Read first.** `server/models/job_spend.py` (InstancePool models),
`server/config/config_loader.py` (`pool_table_name`), `config/app.dev.config`.

**Modify.**
- `server/models/job_spend.py` — append the 6 models. `total_cost` is a plain
  field (not computed — `cloud_cost` is None in v1). `created_by`/`run_as`/
  `pipeline_type` are `Optional[str]`. Add `workload_type: str`,
  `compute_mode: str`, `cost_basis: str`, `metadata_missing: bool`.
  `PipelineSummaryMetrics` carries `serverless_spend`, `classic_spend`, **and
  `mixed_spend`** (three-bucket split per §5.3) plus `mixed_pipelines`.
- `server/config/config_loader.py` — add `pipeline_table_name` property
  (mirrors `pool_table_name`) + `to_dict()`.
- `config/app.dev.config` — add `pipeline_table_name =
  dbspend360.04june.dbspend360_total_pipeline_spends`.

**Exit criteria.**
1. `uv run python -c "from server.models.job_spend import GroupedPipeline;
   print(GroupedPipeline.model_json_schema())"` runs.
2. `uv run python -c "from server.config.config_loader import app_config;
   print(app_config.pipeline_table_name)"` prints the FQN.

### CP6 — Backend service methods

**Read first.** `server/services/databricks_service.py` (the instance-pool
methods), the CP5 models.

**Modify.** `server/services/databricks_service.py`:
- `__init__`: `self.pipeline_table_name = app_config.pipeline_table_name`.
- `get_pipelines_grouped()` — SQL §5.1 (deterministic `compute_mode`/
  `cost_basis`, optional `workload_type` filter).
- `get_pipeline_summary_metrics()` — SQL §5.3 (mode split sums to total;
  serverless/classic `$` split; per-workload `$` breakdown).
- `get_top_pipelines()` — top-N by total cost.
- `_get_batch_pipeline_days()` — SQL §5.2; service groups by pipeline.
- `get_pipeline_details(pipeline_id, workspace_id=None)` — reads config from
  `system.lakeflow.pipelines` (most-recent via QUALIFY); sentinel
  `metadata_missing=True` when absent. Scopes by `workspace_id` when supplied;
  raises an ambiguity error (→ router 409) if omitted and the id spans >1
  workspace. **No REST API.**
- `get_pipeline_cost_summary(pipeline_id, workspace_id=None)` — aggregates +
  `cost_basis` + `workload_type` for the analyze endpoint; same
  `workspace_id` scoping.

**Exit criteria.**
1. Each method exercised via `uv run python -c` against dev.
2. `_get_batch_pipeline_days` days sum to the pipeline total (± float
   tolerance).
3. `get_pipeline_details('made-up-id')` returns `metadata_missing=True`, no
   exception.
4. A real DLT pipeline returns non-NULL `created_by`.
5. Summary `serverless_pipelines + classic_pipelines + mixed_pipelines ==
   total_pipelines`.

### CP7 — Backend router, LLM method, app wiring

**Read first.** `server/routers/instance_pools.py`,
`server/services/llm_service.py` (`analyze_cluster_configuration`),
`server/app.py` (the `StaticFiles` mount comment).

**Create / modify.**
- `server/routers/pipelines.py` (new) — 6 endpoints per §6,
  `APIRouter(prefix="/api/pipelines", tags=["pipelines"])`.
- `server/services/llm_service.py` — append `PIPELINE_ANALYSIS_PROMPT` +
  `analyze_pipeline_costs`. Built on `CLUSTER_ANALYSIS_SYSTEM_PROMPT`;
  declarative-pipeline guidance; the prompt receives `cost_basis` and **must
  state the DBU-only caveat when `cost_basis != 'full'`** and must not
  recommend cloud-VM changes on numbers it knows are DBU-only. Output: 5
  sections, ≤3 recommendations.
- `server/app.py` — import + `include_router(pipelines_router)` **above**
  `StaticFiles`.

**Exit criteria.**
1. `nohup ./watch.sh > /tmp/databricks-app-watch.log 2>&1 &` → `Application
   startup complete.`
2. All 6 endpoints return 200 (per CLAUDE.md FastAPI verification):
   ```bash
   curl -s "http://localhost:8000/api/pipelines/health" | jq
   curl -s "http://localhost:8000/api/pipelines/summary?start_date=2026-05-24&end_date=2026-06-23" | jq
   curl -s "http://localhost:8000/api/pipelines/grouped?start_date=...&end_date=...&page=1&per_page=10" | jq
   curl -s "http://localhost:8000/api/pipelines/grouped?...&workload_type=DLT%20Pipeline" | jq
   curl -s "http://localhost:8000/api/pipelines/top-pipelines?start_date=...&end_date=...&limit=5" | jq
   curl -s "http://localhost:8000/api/pipelines/{id}/details" | jq
   curl -s "http://localhost:8000/api/pipelines/{id}/analyze" | jq
   ```
3. `total_count` on `/grouped` equals `COUNT(*)` of the group-level SQL.
4. `/{id}/analyze` for a classic pipeline includes the DBU-only caveat;
   for a serverless pipeline it does not falsely add one.

### CP8 — Frontend Dashboard tab extension

**Read first.** `client/src/components/Dashboard.tsx`,
`client/src/components/ui/tabs.tsx`.

**Modify.** `Dashboard.tsx`: extend `VALID_TABS` with `'pipelines'`, add the
4th `<TabsTrigger value="pipelines">Pipeline Compute</TabsTrigger>` and a 4th
`<TabsContent value="pipelines">` placeholder. No edits to URL-state
machinery.

**Exit criteria.**
1. Watch picks up the change, no TS errors.
2. Existing three tabs are visually identical.
3. Clicking the placeholder swaps the panel; refresh on `?tab=pipelines` lands
   back on it.

### CP9 — Frontend types + API client + hooks

**Read first.** `client/src/types/instance-pool.ts`,
`client/src/lib/api-client.ts`, `client/src/hooks/useInstancePools.ts`.

**Create / modify.** `client/src/types/pipeline.ts` (new),
`client/src/lib/api-client.ts` (append 5 methods + `workload_type` param),
`client/src/hooks/usePipelines.ts` (new).

**Exit criteria.**
1. `tsc --noEmit` (via watch) passes.
2. `fetch('/api/pipelines/summary?...')` returns data satisfying the
   interfaces.

### CP10 — Frontend PipelineDashboard UI

**Read first.** `client/src/components/InstancePoolsDashboard.tsx`,
`InstancePoolsTable.tsx`, `InstancePoolsSummaryCards.tsx`,
`InstancePoolFilterControls.tsx`, `InstancePoolDetailsModal.tsx`.

**Create / modify.** `PipelineDashboard.tsx`, `PipelineSummaryCards.tsx`,
`PipelinesTable.tsx`, `PipelineFilterControls.tsx`, `PipelineDetailsModal.tsx`
(all new); replace the `pipelines` placeholder in `Dashboard.tsx` with
`<PipelineDashboard />`.

**Implementation notes.** Expansion state is one `Set<string>`. **Three truth
indicators rendered:** (a) `workload_type` badge per row + workload `$`
breakdown in the summary + filter chips; (b) `cost_basis` info-icon/tooltip on
the `$` (only for `dbu_only`/`partial`); (c) §3.5 neutral "Metadata not
available" badge. Summary footnote states the serverless/classic split in
plain numbers. Global tab footnote: list price, excludes cloud VM (classic) +
discounts, instance-pool overlap.

**Exit criteria.**
1. Playwright walk: open app → Pipeline Compute tab → summary cards with the
   workload breakdown (DLT vs SQL-MV …) and the serverless/classic footnote →
   filter to "DLT Pipeline" → expand first pipeline → per-day breakdown →
   click name → details modal with the LLM analysis (DBU-only caveat present
   for a classic pipeline).
2. `workload_type` badges, `cost_basis` info-icons, and the neutral
   "Metadata not available" badge all render correctly.
3. No console errors.

### CP11 — Deploy + post-deploy verification

**Steps.** `./deploy.sh`; then per CLAUDE.md: `uv run python dba_logz.py
<app-url> --search "Application startup complete\|Uvicorn running" --duration
60`; then `uv run python dba_client.py <app-url> /api/pipelines/health` and the
other 5.

**Exit criteria.**
1. Log stream: `Application startup complete.` / `Uvicorn running`, no
   exceptions.
2. All 6 endpoints 200; aggregate endpoints return non-zero data for the
   30-day window.
3. Browser smoke: Pipeline Compute tab renders end-to-end with prod data; the
   workload breakdown is visible and non-trivial.

## 9. Acceptance criteria

1. **No regression on existing tabs.** Job/All-Purpose/Instance Pools
   byte-identical (visual diff); their test scripts pass unchanged.
2. **Tab navigation.** Selecting "Pipeline Compute" swaps the panel without
   reload; `?tab=pipelines` preserved on refresh.
3. **Filter correctness.** Every rollup row has a non-null `pipeline_id`;
   nothing is dropped by `billing_origin_product` (it only *labels*). Asserted
   in `claude_scripts/test_pipeline_filter.py`.
4. **Workload dimension (exact).** Distinct `workload_type` values include at
   least `DLT Pipeline` and `DBSQL Materialized View`; the per-workload `$`
   breakdown sums to `total_spend` **and** — because `billing_origin_product`
   is kept in the rollup grain (§3.3) — reconciles row-for-row with the
   staging table's per-product `SUM` (no dominant-product approximation).
   Asserted in `claude_scripts/test_pipeline_workload_split.py`.
5. **Serverless captured.** ≥1 row has `compute_mode = 'serverless'`
   (the whole point of §3.1).
6. **Cost integrity + idempotent MERGE.** `SUM(databricks_cost)` of the rollup
   equals the staging table for the same window; **re-running the staging
   collector over an overlapping window leaves row count and `SUM` unchanged**
   (null-safe `cluster_id` MERGE, §3.3/§5.4 — serverless rows update in place
   instead of re-inserting). Asserted in
   `claude_scripts/test_pipeline_merge_idempotent.py`.
7. **`cost_basis` honesty.** `cost_basis = 'full'` ⇔ `compute_mode =
   'serverless'`; `'dbu_only'` ⇔ `'classic'`; `'partial'` ⇔ `'mixed'`; never
   NULL. Asserted in `claude_scripts/test_pipeline_cost_basis.py`.
8. **`cloud_cost` v1 invariant.** `COUNT(*) WHERE cloud_cost IS NOT NULL` = 0.
9. **Three-state metadata.** `metadata_missing = TRUE` rows have
   `pipeline_name LIKE 'Pipeline %'` AND `pipeline_deleted_at IS NULL`; deleted
   rows have `metadata_missing = FALSE`; column never NULL. The summary
   "metadata unavailable" KPI excludes Vector Search.
10. **Endpoint contracts.** Each of the 6 returns 200 with the documented
    shape; `total_count` matches the CTE `COUNT(*)`.
11. **Drill-down.** Each `GroupedPipeline.days` sums to the row's `total_cost`
    (± 0.01 USD). Asserted in `claude_scripts/test_pipeline_drill_down.py`.
12. **KPI math.** `serverless_pipelines + classic_pipelines + mixed_pipelines
    == total_pipelines` (no double-count from mode-switchers) **and**
    `serverless_spend + classic_spend + mixed_spend == total_spend` (± 0.01 USD;
    the `$` split is exhaustive of three buckets, not two — §5.3). Asserted in
    `claude_scripts/test_pipeline_summary_math.py`.
13. **Owner attribution.** `created_by` populated for active DLT pipelines in
    both `/grouped` and `/{id}/details` (human email, no GUID).
14. **LLM honesty.** `/api/pipelines/{id}/analyze` returns a 5-section
    analysis; includes the DBU-only caveat iff `cost_basis != 'full'`.
    Asserted in `claude_scripts/test_pipeline_analysis.py`.
15. **Deploy health.** Deployed log stream clean; live `/api/pipelines/summary`
    returns non-zero `total_pipelines` for the 30-day window.

## 10. Risks & mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Users read the tab total as "DLT spend" | Medium | `workload_type` is a first-class badge + KPI split + filter; the headline shows the breakdown, not one number. Tab named "Pipeline Compute", not "DLT". |
| Classic cloud-VM cost omitted misleads | Low (4% of spend) | Per-row `cost_basis` info-icon ("DBU only — excludes cloud VM"); summary footnote with the serverless/classic split; LLM caveat. Not hidden — labelled. |
| List price ≠ invoiced rate | Medium (app-wide) | Tab footnote states "list price, excludes account discounts". Pre-existing; disclosed. v2 could read `system.billing.usage_prices` if available. |
| `billing_origin_product` enum evolves / new product | Low-Medium | Used only to *label*, never to *filter*. Unknown values fall back to the raw string ("never dropped"). |
| Price-join SKU drift silently undercounts | Low (0 in §0) | Inner join + explicit `PRICE_JOIN_DROP` guard log (§5.4); 0 NULL prices observed. |
| `system.lakeflow.pipelines` Regional → inflated "missing" for multi-region | Medium multi-region | Neutral "Metadata not available" badge (not alarming); KPI excludes products that never have metadata; README + tooltip note the regional limit. v2: per-region UNION (§13). |
| Vector Search etc. clutter a "DLT" mental model | Medium | Workload filter chips let the user narrow to DLT instantly; default can be set to DLT-highlighted if desired. |
| Double-count with Instance Pools (classic on pool) | Low ($3.7K/30d) | Disclosed in README + footnote; not de-duplicated in v1 (§3.7). |
| `pipeline_id` collisions across workspaces | Low — handled | Table key + SCD partition include `workspace_id`; `/{id}/details` and `/{id}/analyze` take an optional `workspace_id` query param and return HTTP 409 (not a silent wrong-workspace pick) if an ambiguous id is requested without it (§6). |
| `StaticFiles` mount swallows `/api/pipelines/*` | Low | `include_router` **above** the mount; `/api/pipelines/health` smoke test. |
| Auto-generated TS client shadows types | Low | Components import from `@/types/*` + `@/lib/api-client`; additive only. |

## 11. Rollback

Per-layer, in priority order:
1. **UI bug only** — revert frontend commits; backend + pipeline stay.
2. **Backend regression** — revert the `app.py` `include_router` line; router
   404s, rest untouched.
3. **Pipeline data quality** — `dbspend360_total_pipeline_spends` /
   `dbspend360_pipeline_dbu_cost` are new tables; `DROP TABLE` + rerun. No
   existing-table migration.
4. **LLM prompt regression** — revert the prompt diff.

No data migration on existing tables. Fully reversible.

## 12. Effort estimate

~12–14 hours (the broad/product-dimensioned scope adds ~3h over the original
DLT-only estimate, concentrated in the rollup derivations, the summary
workload-split query, and the UI's workload chips + cost-basis indicators).

| Checkpoint | Hours | Notes |
|---|---|---|
| CP1 — DDLs + register | 0.75 | Two tables, more columns (cluster_id, splits, dimensions) |
| CP2 — Staging pipeline | 1.5 | Inner join + guard, update/maint split, cluster_id grain |
| CP3 — Rollup pipeline | 1.25 | `compute_mode`/`cost_basis`/`workload_type` derivation + SCD join |
| CP4 — DAB wiring + dev run | 1 | End-to-end run |
| CP5 — Models + config | 0.5 | Append-only |
| CP6 — Service methods | 1.5 | Deterministic SQL + summary split math |
| CP7 — Router + LLM + curl | 1.75 | LLM cost-basis caveat + FastAPI verification |
| CP8 — Dashboard tab | 0.25 | One-line trigger + panel |
| CP9 — Types + client + hooks | 0.75 | + `workload_type` param |
| CP10 — Pipeline UI | 2.5 | Workload chips + cost-basis icons + neutral badge + footnotes |
| CP11 — Deploy + verify | 0.75 | Standard flow |
| Buffer | 1 | Preview schema reconciliation, type cleanup |

## 13. Out of scope, captured for follow-up

- **Cloud cost integration (v2).** For classic pipelines (~4%), join
  `dbspend360_cloud_cost_explorer` (tagged by `cluster_id`, already kept in
  staging) into the rollup; un-hide `cloud_cost`; flip `cost_basis` to `full`
  for those rows; drop the LLM caveat.
- **Update vs maintenance split surfacing (v2).** `update_cost` /
  `maintenance_cost` already land in staging (§3.6) — surface a "maintenance
  ratio" KPI + per-update drill-down (`dlt_update_id`, joining
  `system.lakeflow.pipeline_update_timeline`). No re-ingest.
- **Effective/discounted pricing (v2).** Replace list price with the
  customer's negotiated rate so the figure matches the invoice.
- **Per-workload deep views (v2).** Dedicated lenses per `workload_type`
  (e.g. MV refresh cadence for SQL, sync lag for Online Tables).
- **Per-table cost attribution.** Not natively possible (billing is at the
  pipeline/update level). Guidance, not a feature.
- **`created_by` SP-ID → display name (v2).** Resolve service-principal IDs via
  SCIM.
- **Continuous vs triggered classification (v2).** From `settings`/
  `configuration` in `system.lakeflow.pipelines`.
- **Multi-region snapshot resolution (v2).** Per-region SCD-collapse + UNION.
- **"All compute" combined view** — a 5th tab combining all four categories
  with explicit double-count subtraction. Separate PR.
- **Alerts / budgets per pipeline.**
- **Promote `claude_scripts/test_pipeline_*` to real pytest** — same CI-wiring
  blocker as the other tabs.
