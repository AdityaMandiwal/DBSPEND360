# Plan: Subscription-scoped coverage labeling + banner across ALL cost tabs

> Status: proposed · Scope: every cost tab (Job Clusters, All-Purpose, Pipeline
> Compute, Instance Pools) · Cloud: Azure

## Intent (what problem we are solving)

The reported symptom — most "Shared" clusters on the All-Purpose tab show `—` for
Azure cost — is one visible face of a **systemic** issue that affects **every cost
tab**. DBU cost is account-wide, but **Azure cloud cost is only ingested for a
single Azure subscription**, so any cluster/pool whose workspace lives in another
subscription has DBU but no cloud cost to join to → `—`, and its true VM spend is
invisible. Today that `—` is indistinguishable from the legitimate in-coverage
`—` (pool-backed / serverless / not-yet-landed), so a real structural gap looks
like ordinary missing data.

**Product principle (decided):** never remove a workspace that has DBU. DBU from
`system.billing.usage` is a **complete, authoritative measurement** — a
cross-subscription workspace's DBU is correct even when its VM cost is
unreachable. We therefore **keep every DBU-bearing row** and instead make the
*cloud-cost cell* tell the truth about **why** it is empty:

1. **Covered** workspace, cloud cost present → the dollar value.
2. **Covered** workspace, cloud cost `NULL` → existing `—` (pool / serverless /
   not-yet-landed — unchanged semantics).
3. **Not-covered** workspace (has DBU, data-plane in another subscription) →
   **"Not covered"** label + tooltip. The DBU shown is still complete.

**We do not filter rows out.** The old "show only the intersection" rule is
replaced by "**tag, don't drop**": show everything, label the cloud gap per row,
and surface the aggregate gap (workspace count + uncosted DBU dollars) in a
persistent banner so the scale of the cross-subscription spend is impossible to
miss and stays **actionable** (it is the forcing function for the multi-sub RBAC
ask in Future work).

We keep the pipeline **single-subscription for now**; multi-subscription
ingestion is follow-up work gated on cross-subscription access (see Future work).
When it lands, covered flags flip to true and the banner shrinks automatically —
no row ever appears or disappears.

> **Everything is parameterized — nothing environment-specific is hardcoded.**
> The queried subscription(s) and scope are **job widgets**; the covered
> workspace set is **discovered from ARM at pipeline runtime**; and the excluded
> workspaces, their per-tab DBU totals, and the example names shown in the banner
> are **computed at read time** from system tables + the rollups' coverage flag.
> No workspace name, dollar figure, or subscription id ever appears in a
> notebook, the backend, or the UI. The specific numbers in this document are an
> **illustrative snapshot of one deployment** (see
> [Investigation snapshot](#investigation-snapshot-this-deployment-only)) — they
> are evidence, not design inputs, and will differ on every deployment.

> **Why not filter?** Removing legitimate DBU from primary views trades a visible
> data-quality question (a `—` that provokes "why?") for an invisible one
> (absence that reads as "complete"). It also (a) breaks any aggregate/downstream
> total silently, (b) creates a trust regression as rows users see today vanish,
> and (c) treats cross-subscription DBU-only rows differently from serverless
> DBU-only rows (Pipeline tab), which are already shown as first-class. Labeling
> keeps every number honest without discarding correct data.

## Root cause (evidence-backed)

The Shared / Dedicated badge is cosmetic — it is `data_security_mode` and is
**never used in any cost join** (`client/src/components/AllPurposeClustersTable.tsx`).

Every tab is built the same way: account-wide DBU (`system.billing.usage`)
LEFT/INNER-joined on the resource id to a **single-subscription** Azure Cost
Management pull (`jobs/notebooks/azure_cloud_cost_explorer_app.ipynb`), keyed by
the `clusterid` / `DatabricksInstancePoolId` tag. No match → cloud cost stays
`NULL` and the UI renders `—` (`client/src/lib/all-purpose-display.ts`).

| Tab | Rollup table | Cloud join key |
|---|---|---|
| Job Clusters | `dbspend360_total_job_spends` | `cluster_id` |
| All-Purpose | `dbspend360_total_all_purpose_spends` | `cluster_id` |
| Pipeline Compute | `dbspend360_total_pipeline_spends` | `cluster_id` |
| Instance Pools | `dbspend360_total_pool_spends` | `instance_pool_id` |

Findings (mechanism — deployment-independent; verified against live data + a
one-off ARM discovery run using the pipeline's own service principal; concrete
numbers for the reference deployment are quarantined in the
[Investigation snapshot](#investigation-snapshot-this-deployment-only)):

- **Not pools, not the badge.** The dashing "Shared" clusters are overwhelmingly
  **not** pool-backed and the badge is irrelevant; most are service clusters in
  **out-of-subscription workspaces**.
- **The SP sees exactly one subscription.** Within it, each workspace's data-plane
  is a `databricks-rg-*` **managed resource group**. ARM
  `Microsoft.Databricks/workspaces` returns nothing and the managed RGs are
  deny-locked, so the numeric `workspace_id` is **not** recoverable from Azure —
  only the RG/workspace **name** is.
- **Bridge:** `system.access.workspaces_latest` (`workspace_id`,
  `workspace_name`, `workspace_url`) maps that name → numeric `workspace_id`. A
  small tail of managed-RG names may not match (deleted/recreated workspaces).
- **The big uncosted spend is genuinely cross-subscription:** the high-DBU,
  zero-Azure workspaces (typically staging/prod workspaces) resolve to managed
  RGs **outside** the queried subscription. Only in-subscription workspaces get
  cloud cost attributed.
- **Magnitude is material and spans every tab.** A large share of DBU sits in
  workspaces with zero Azure attribution, almost entirely due to
  cross-subscription placement. The gap exists on Job, All-Purpose, Pipeline, and
  Pools alike — **and its size differs per tab** (a workspace can be job/pipeline
  heavy but have little interactive spend, or vice-versa), so excluded-DBU totals
  must be computed **per tab at runtime**, never quoted as one shared figure.

## Investigation snapshot (this deployment only)

> **Illustrative, not design inputs.** Every value below is specific to the
> reference deployment at the time of investigation and **will differ on any
> other deployment**. Nothing here is hardcoded anywhere in the pipeline,
> backend, or UI — it is all rediscovered/recomputed at runtime (see the
> parameterization note in [Intent](#intent-what-problem-we-are-solving)). Kept
> only so the mechanism above has a concrete example and so the magnitudes are
> auditable.

Reference deployment (subscription id redacted as `<sub>`), verified via
`claude_scripts/verify_coverage_gap.py` against system tables:

- **SP scope:** one subscription (`<sub>`), ~506 `databricks-rg-*` managed RGs
  (~491 distinct names). Name → `workspace_id` bridge matched **~483/491**; the
  ~8 misses were the pre-flight gate (Phase 0).
- **`workspace_covered` vs `all-product` vs `all-purpose` — the key correction:**
  the headline ">$1M uncosted DBU" is an **all-product, cross-tab** figure, not an
  All-Purpose figure. Measured over a 730-day window:

  | Bucket | DBU $ | Note |
  |---|---|---|
  | Top cross-subscription workspaces (all-product) | **>$2.7M** combined | staging + prod workspaces, all confirmed outside `<sub>` |
  | All-Purpose DBU, non-home workspaces | **~$274K** | the *All-Purpose tab's* actual excluded DBU — far below $1M |
  | All-Purpose DBU, home in-sub workspace | ~$769K | legitimately covered |

  The largest single cross-subscription workspace (~$1.19M all-product) barely
  appears on the All-Purpose tab — it is job/pipeline-heavy. **This is exactly why
  the banner's excluded-DBU total must be per-tab and runtime-computed:** the same
  workspace is a huge "Not covered" row on Job/Pipeline and a negligible one on
  All-Purpose.

- **Reproduce:** `DBSPEND_WINDOW_DAYS=730 uv run python
  claude_scripts/verify_coverage_gap.py` (reads warehouse/schema from env; no
  names or figures baked into the script logic — it prints whatever the current
  deployment contains).

## Design decision

**Per-row coverage flag + persistent banner, from one shared source of truth.
Tag, don't drop. Single subscription for now.**

- **Coverage is workspace-level.** A workspace is *covered* iff its data-plane is
  in the queried subscription. Derived once from managed-RG names →
  `system.access.workspaces_latest`, not empirically from "which clusters got a
  cost match" (that would bake in structural per-cluster misses).
- **Materialize one boolean per row.** Compute `workspace_covered` in each
  **DBU-stage** notebook (they all carry `workspace_id` from
  `system.billing.usage`) via a LEFT JOIN to the covered-workspace table, then
  carry that single boolean through the rollup into the app-read table. This
  replaces the originally-planned `WHERE workspace_id IN (…)` **filter** in the
  same notebooks — same touch points, opposite operation (tag instead of drop).
  - *Why the DBU stage:* the job and all-purpose rollup tables do **not** retain
    `workspace_id` at their grain (verified — job DDL keeps `cluster_id` only), so
    the join cannot happen at the rollup. Carrying a lightweight boolean is
    cheaper than re-adding `workspace_id` to every grain.
- **Cell rendering distinguishes the two empty states.** `workspace_covered =
  false` → "Not covered"; covered & `NULL` → existing `—`; covered & value → the
  number. The existing NULL-not-`0.0` honesty rule and the per-cell `—` tooltip
  are unchanged.
- **`/api/coverage` powers aggregates, not cells.** The banner and any KPI
  segmentation read the aggregate excluded set (count + **per-tab** uncosted DBU +
  example names, all computed at read time) from one endpoint; individual cells
  never do a lookup — they use the per-row boolean. Excluded DBU is **per tab**
  because the same cross-subscription workspace can be large on one tab and
  negligible on another (see the [Investigation snapshot](#investigation-snapshot-this-deployment-only)).
- **Never silently understate a headline.** Summary/KPI aggregates must not blend
  a not-covered row's DBU-only `total_cost` into a "complete total." Show covered
  total cost, plus a **separate** "DBU in non-covered workspaces" figure that
  ties to the banner.

## Coverage field & label contract

| Layer | Artifact | Value |
|---|---|---|
| Rollup tables | new column `workspace_covered BOOLEAN` | `true` = data-plane in queried subscription |
| Tab APIs | per-row field `workspace_covered: bool` | passed straight from the rollup |
| `/api/coverage` | aggregate (all values runtime-computed) | **Single call, no params**, returns the full map: `{ covered_subscription_ids: [...], covered_workspace_count, excluded_workspaces: [{workspace_id, workspace_name, dbu_dollars}], excluded_dbu_by_tab: {job, all_purpose, pipeline, pool}, currency }`. Fetched once and cached; each tab's banner reads its own key from `excluded_dbu_by_tab` (one fetch shared across all four banners). |
| Cell (all tabs) | label | `"Not covered"` when `workspace_covered === false` and cloud cost is empty |
| Cell tooltip | shared constant | *"Cloud (VM) cost isn't available for this workspace — it runs in a different Azure subscription than the one DBSpend360 ingests. The DBU cost shown is complete."* |

"Not covered" reuses the plan's own coverage vocabulary end-to-end (banner ↔
cell). It is deliberately **distinct** from `—` so the two empty states never
re-merge into one ambiguous symbol.

## Implementation phases

### Phase 0 — Pre-flight verification (gate before any code)

- **Premise check (runnable now, done):** `claude_scripts/verify_coverage_gap.py`
  confirms from system tables that material DBU sits in cross-subscription
  workspaces and that the magnitude is **per-tab** (all-product ≫ all-purpose).
  This needs no ARM access — it reads warehouse/schema from env and prints
  whatever the current deployment contains.
- **Name-match gate (needs Phase 1 discovery first):** the exact set of unmatched
  managed-RG names comes from the ARM discovery, whose output is **not persisted**
  today. Once Phase 1 writes `dbspend360_covered_workspaces`, confirm the
  unmatched tail is not high-DBU (join usage × `workspaces_latest`); characterize
  any material miss before shipping, since it would otherwise be mislabeled.

### Phase 1 — Build the shared covered-workspace map (new notebook + DDL)

Productize the throwaway `mode=discover` probe used during investigation.

- **New DDL** `jobs/ddls/dbspend360_covered_workspaces.ipynb` → table
  `dbspend360_covered_workspaces (workspace_id STRING, workspace_name STRING,
  subscription_id STRING, workspace_url STRING, updated_at TIMESTAMP)`.
- **New notebook** `jobs/notebooks/dbspend360_covered_workspaces_app.ipynb`:
  1. Reads `scope` + `subscription_id` widgets, builds `ClientSecretCredential`,
     gets an ARM token (`https://management.azure.com/.default`).
  2. Lists resource groups, keeps `databricks-rg-*`, reads each RG's `managedBy`
     to recover the workspace name.
  3. Joins names (case-insensitive) to `system.access.workspaces_latest` →
     numeric `workspace_id` + `workspace_url`.
  4. MERGE-overwrites `dbspend360_covered_workspaces`.
  - Read-only against Azure (ARM GETs); writes only its own table; reuses
    `utils_common` audit/logging. Runs **before** all DBU rollups in the DAG.
- **Degradation signal:** emit a row count + a warning (audit log / job metric)
  when a workspace with usage in `system.billing.usage` is absent from the
  covered set, so coverage silently shrinking (new workspace, renamed RG) is
  observable rather than invisible.
- **Empty-table guard (Azure):** `add_workspace_covered()` in `utils_common`
  logs a warning when `dbspend360_covered_workspaces` is empty but the
  `subscription_id` widget is set (Azure deployment before first discovery).
  AWS/GCP behavior is unchanged (empty table → all rows tagged covered). The
  DAB hard-orders `covered_workspaces` before every DBU rollup task so the
  table should be populated before any tagging runs in normal operation.

> Managed RGs are deny-locked, so VM tags are unreadable — the
> `workspaces_latest` bridge is required (numeric ids come from Databricks).

### Phase 2 — Tag every row with `workspace_covered` (DBU stage → rollup)

For each DBU-stage notebook, **LEFT JOIN** `dbspend360_covered_workspaces` on
`workspace_id` and add a boolean column (no rows dropped):

```sql
CASE WHEN cw.workspace_id IS NOT NULL THEN true ELSE false END AS workspace_covered
```

- `jobs/notebooks/dbspend360_all_purpose_dbu_cost_app.ipynb`
- `jobs/notebooks/dbspend360_dbu_cost_app.ipynb` (Job Clusters)
- `jobs/notebooks/dbspend360_pipeline_dbu_cost_app.ipynb`
- `jobs/notebooks/dbspend360_pool_dbu_cost_app.ipynb` (Instance Pools)

Then **carry `workspace_covered` through** the rollup so it lands on the app-read
tables:

- Add `workspace_covered BOOLEAN` to the four rollup DDLs
  (`dbspend360_total_{job,all_purpose,pipeline,pool}_spends`).
- Propagate the column in the `*_spends_app.ipynb` selects
  (`databricks_job_spends_app`, `all_purpose_spends_app`, `pipeline_spends_app`,
  `pool_spends_app`). The join **logic** is unchanged — only one column is added.

The existing NULL-not-`0.0` join rule is untouched: inside a covered workspace `—`
still legitimately means pool / serverless / not-yet-landed.

> Pools grain is `instance_pool_id`; a pool maps to one workspace, so tag the pool
> at the DBU stage the same way. For the per-cluster drill-down rows, inherit the
> pool's `workspace_covered`.

### Phase 3 — Backend: per-row field + coverage aggregate

- **Per-row field:** expose `workspace_covered` on each tab's existing row model /
  response (`server/routers/{dashboard,all_purpose,instance_pools,pipelines}.py`
  + `server/services/databricks_service.py`). Straight pass-through from the
  rollup column — no lookup.
- **Aggregate endpoint:** add `GET /api/coverage` returning the excluded-set
  summary (schema in the contract table above). Compute the excluded set as
  workspaces with usage in `system.billing.usage` that are **not** in
  `dbspend360_covered_workspaces`, with names via `workspaces_latest`. Compute
  **excluded DBU per tab** as `SUM(databricks_cost) WHERE workspace_covered =
  false` on each rollup table (so each tab's banner reflects that tab's real gap).
  Persist as `dbspend360_coverage_summary` or compute read-time. **One call, no
  params** — returns the full per-tab map; the client fetches once, caches, and
  each banner reads its own key (no per-tab round-trips). All values are derived —
  no names/figures are literals. Verify with `curl` before wiring the UI.

### Phase 4 — Frontend: "Not covered" cells + persistent banner + KPI segmentation

- **Shared label/tooltip constant.** Add `CLOUD_NOT_COVERED_NOTE` (and the
  `"Not covered"` string) once — either a new shared module or mirrored into
  `all-purpose-display.ts`, `pool-display.ts`, `pipeline-display.ts` (wording is
  identical across tabs).
- **Cell branch (all four tabs).** Update the cloud-cost cell to branch on
  coverage first:
  - `CloudCostValue` in `AllPurposeClustersTable.tsx` (+ `AllPurposeUsersTable.tsx`)
  - `PoolCloudCostCell` in `InstancePoolsTable.tsx`
  - inline cells in `PipelinesTable.tsx` (daily expansion)
  - job-clusters cloud cells (`GroupedJobTable.tsx`, including expanded runs)

  ```
  workspace_covered === false            → "Not covered"  + CLOUD_NOT_COVERED_NOTE
  workspace_covered === true && value==null → "—"         + existing MISSING_NOTE
  otherwise                              → formatCurrency(value)
  ```
- **Persistent coverage banner (per-tab, fully data-driven).** Shared
  `<CoverageBanner/>` consuming `/api/coverage`, rendered on all four tab
  dashboards, showing **that tab's** excluded workspace count + excluded DBU +
  a few example names — **all interpolated from the endpoint response, never
  hardcoded**. **Non-dismissible** (may collapse to a one-line summary, but never
  permanently hidden) so the excluded total stays visible. Template (values in
  `{…}` come from the API): *"Azure cost covers {covered_subscription_count}
  subscription(s). {n} workspaces (\${excluded_dbu_for_this_tab} DBU) run in other
  subscriptions and show 'Not covered' for cloud cost — e.g. {example_names}."*
- **KPI segmentation.** In the summary cards, keep not-covered rows out of any
  "complete total cloud/total cost" headline, and add a separate "DBU in
  non-covered workspaces" figure that reconciles to the banner. (Cloud-cost
  aggregates are already NULL-safe; the risk is only the blended `total_cost`.)

### Phase 5 — DAB wiring + verify

- `jobs/resource_templates/DBSPEND360.yaml`: add the covered-workspaces DDL + app
  tasks, ordered **before** all DBU rollups; deploy per the deployment-paths rule
  under `.../deployed from cursor/jobs/...`.
- Run the full DAG; confirm: every rollup table has `workspace_covered`
  populated, **no rows dropped**, cross-subscription rows render "Not covered"
  (not `—`), in-coverage `—` still appears where expected, the banner lists the
  excluded workspaces + DBU, and KPI headlines don't understate. Validate in dev
  right after Phase 2 (diff row counts = unchanged) before touching the UI.

## Files touched

| File | Change |
|---|---|
| `jobs/ddls/dbspend360_covered_workspaces.ipynb` | **new** — covered-workspace table DDL |
| `jobs/notebooks/dbspend360_covered_workspaces_app.ipynb` | **new** — ARM managed-RG discovery → `workspaces_latest` bridge → write table + degradation signal |
| `jobs/notebooks/dbspend360_all_purpose_dbu_cost_app.ipynb` | LEFT JOIN covered map → add `workspace_covered` |
| `jobs/notebooks/dbspend360_dbu_cost_app.ipynb` | LEFT JOIN covered map → add `workspace_covered` |
| `jobs/notebooks/dbspend360_pipeline_dbu_cost_app.ipynb` | LEFT JOIN covered map → add `workspace_covered` |
| `jobs/notebooks/dbspend360_pool_dbu_cost_app.ipynb` | LEFT JOIN covered map → add `workspace_covered` |
| `jobs/ddls/dbspend360_total_{job,all_purpose,pipeline,pool}_spends.ipynb` | add `workspace_covered BOOLEAN` column |
| `jobs/notebooks/{databricks_job,all_purpose,pipeline,pool}_spends_app.ipynb` | propagate `workspace_covered` in select |
| `jobs/resource_templates/DBSPEND360.yaml` | add covered-workspaces tasks (before DBU rollups) |
| `server/routers/*`, `server/services/databricks_service.py` | per-row `workspace_covered` + `GET /api/coverage` |
| `client/src/lib/{all-purpose,pool,pipeline}-display.ts` (or one shared module) | `CLOUD_NOT_COVERED_NOTE` + `"Not covered"` |
| `client/src/components/{AllPurposeClustersTable,AllPurposeUsersTable,InstancePoolsTable,PipelinesTable}.tsx` + job table | cell branch on `workspace_covered` |
| `client/src/components/` (new `CoverageBanner`) + 4 tab dashboards + summary cards | render banner + KPI segmentation |

Reused unchanged: all `*_spends_app.ipynb` **join logic** (only one column added),
the LEFT/INNER NULL-not-`0.0` rule, the existing per-cell `—` tooltip,
`utils_common.ipynb`, and the Shared/Dedicated badge.

## Scope guardrails (what will NOT change)

- **No rows are removed** from any rollup or view — DBU-bearing workspaces always
  appear. (This is the core reversal from the earlier filter design and removes
  the trust-regression / downstream-total risks.)
- No change to the Shared/Dedicated badge (it is `data_security_mode`, unrelated).
- No change to the NULL-not-`0.0` rule — in-coverage `—` stays correct and stays
  visually distinct from "Not covered".
- No multi-subscription ingestion in this plan (Future work).
- Coverage is workspace-level; per-cluster `—` inside covered workspaces is
  preserved.

## Future work — multi-subscription ingestion

To *recover* the cross-subscription spend rather than label it:

- Grant the pipeline SP **Cost Management Reader** on the other subscriptions (an
  access/RBAC task — the SP currently sees only one subscription). **Start this
  request in parallel with this plan** — the banner's excluded-DBU figure is the
  justification, and it identifies exactly which subscriptions matter.
- Extend `azure_cloud_cost_explorer_app.ipynb` to loop over multiple
  `(subscription_id, scope)` pairs and union into `dbspend360_cloud_cost_explorer`.
- Grow `dbspend360_covered_workspaces` to the union of queried subscriptions;
  `workspace_covered` flips to `true`, "Not covered" cells become real dollars,
  and the banner shrinks — automatically, across all tabs, with **no row
  appearing or disappearing**.

## Open items to confirm

- Phase 0 name-match gate (post Phase 1): are any unmatched managed-RG names
  high-DBU? (The premise/magnitude check is already done — see Investigation
  snapshot.)
- `workspace_covered` propagation: confirm each `*_spends_app` select carries the
  new boolean through to the rollup grain (job & all-purpose drop `workspace_id`,
  so the boolean must ride through — not re-derived downstream).
- Banner: one shared component across tabs (recommended) vs per-tab copy tuned to
  each resource type.
- Refresh cadence for `dbspend360_covered_workspaces` (daily with the DAG is
  enough; the managed-RG set changes slowly).
- Confirm AWS/GCP deployments want the same coverage labeling (this plan is Azure;
  the pattern generalizes but the discovery mechanism differs per cloud).
