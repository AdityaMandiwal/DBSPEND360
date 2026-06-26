# Plan — EC2 cloud cost for Instance Pools + Pipeline Compute tabs

Branch (proposed): `feat/pool-pipeline-ec2-cost`

## 0. TL;DR

Two tabs ship today as **DBU-only** with a reserved-but-always-`NULL`
`cloud_cost` column: **Instance Pools** and **Pipeline Compute**. Job Clusters
and All-Purpose Clusters already show EC2/EBS. This plan turns on EC2 cost for
the two missing tabs — accurately, with honest per-row notes wherever the cloud
number is structurally absent.

The two tabs are **not the same problem**:

| Tab | Difficulty | Why |
|---|---|---|
| **Pipeline Compute** | Moderate — reuses existing data | Classic pipeline clusters carry a `cluster_id` and are tagged `ClusterId` on AWS, so their EC2 cost is **already in `dbspend360_cloud_cost_explorer`**. We only need to join it in. Serverless pipelines have **no separate EC2 line** by design. |
| **Instance Pools** | Hard — needs a brand-new data source | Pool VMs (especially idle/warm capacity) are tagged `DatabricksInstancePoolId`, **not** `ClusterId`. The existing explorer groups only by `ClusterId`, so pool cloud cost is **structurally invisible** today. Requires a new AWS Cost Explorer query + a new table. |

Both rollup notebooks already contain a `TODO(v2)` join slot and a reserved
`cloud_cost DOUBLE` column, so **no schema migration** is needed on the rollup
tables.

---

## 1. Current state (verified in code)

### 1.1 The cloud-cost source of truth
`dbspend360_cloud_cost_explorer` — produced by
`jobs/notebooks/aws_cloud_cost_explorer_app.ipynb`.

- AWS CE `GetCostAndUsage`, `Granularity=DAILY`,
  `GroupBy = [TAG ClusterId, DIMENSION SERVICE]`,
  `Filter = SERVICE IN ('Amazon Elastic Compute Cloud - Compute', 'EC2 - Other')`
  (EC2-Other folds in EBS), metric `AmortizedCost`.
- Output grain: **`(cluster_id, cost_incurred_date, currency)`**, one `cloud_cost`
  bucket. `compute/storage/network/other_cost` are `NULL` on AWS.
- **Only `ClusterId`-tagged EC2/EBS is captured.** Anything not carrying a
  `ClusterId` tag (idle pool capacity, NAT, S3, ELB, VPC, data transfer) is
  dropped by `utils_common.filter_valid_cost_rows` before MERGE.

### 1.2 Pipeline Compute (DBU-only today)
- Staging `dbspend360_pipeline_dbu_cost` — grain
  `(workspace_id, pipeline_id, usage_date, cluster_id, billing_origin_product)`.
  `cluster_id` is **kept, NULL for serverless** (the serverless signal), so the
  cloud join needs **no re-ingest**.
- Rollup `dbspend360_total_pipeline_spends` (`pipeline_spends_app.ipynb`) —
  collapses `cluster_id` away into `compute_mode`
  (`serverless` / `classic` / `mixed`) and `cost_basis`
  (`full` / `dbu_only` / `partial`). Grain
  `(workspace_id, pipeline_id, usage_date, billing_origin_product)`.
  `cloud_cost = CAST(NULL AS DOUBLE)`, `total_cost = databricks_cost + COALESCE(cloud_cost,0)`.
  There is an explicit `TODO(v2)` slot for a `cluster_id`-keyed cloud join.
- UI: `PipelineSummaryCards.tsx`, `PipelinesTable.tsx`,
  `PipelineDetailsModal.tsx`. KPI strip is "Total DBU Spend (v1: DBU only)".
  `cost_basis` already drives an honesty icon per row.

### 1.3 Instance Pools (DBU-only today)
- DBU `dbspend360_pool_dbu_cost` — grain
  `(instance_pool_id, cluster_id, usage_date, workspace_id)`. `cluster_id` is
  `COALESCE(usage_metadata.cluster_id, '__pool_overhead__')`.
- Rollup `dbspend360_total_pool_spends` (`pool_spends_app.ipynb`) — grain
  `(instance_pool_id, cluster_id, usage_date)`. `cloud_cost = F.lit(None)`, with
  a `TODO(v2)` join slot. `total_cost = databricks_cost + COALESCE(cloud_cost,0)`.
- UI: `InstancePoolsSummaryCards.tsx`, `InstancePoolsTable.tsx`,
  `InstancePoolDetailsModal.tsx`. `InstancePoolsDashboard.tsx` carries an
  explicit "v1 surfaces DBU cost only" disclaimer to remove.

### 1.4 Service / frontend cloud plumbing that already exists (reuse it)
- `server/services/databricks_service.py` already returns `cloud_cost` /
  `total_cloud_cost` for Job Clusters and All-Purpose. The pool and pipeline
  functions deliberately set these to `None`/`0.0`. We flip those.
- Frontend cloud column is gated by `useCloudGate` / `CloudPlatformContext`;
  on AWS it renders a single column labeled **`EC2 / EBS`** (`AWS_CLOUD_LABEL`),
  exactly as the All-Purpose table does. Reuse this — no new label logic.

---

## 2. Goals / non-goals

**Goals**
1. Pipeline Compute tab shows accurate EC2/EBS cost for classic clusters; honest
   `$0`/`N/A` for serverless.
2. Instance Pools tab shows accurate EC2/EBS cost for pool VMs (idle + active).
3. Every figure reconciles to a source of truth within tolerance.
4. Wherever cloud data is structurally absent or hasn't landed, the UI shows a
   short, specific note instead of a misleading `$0` or a blank.

**Non-goals**
- No change to Job Clusters / All-Purpose (already done).
- No Azure/GCP work (this account is AWS; mirror later).
- No proportional allocation of account-wide shared infra (NAT/S3/VPC) onto
  pools or pipelines — that's the separate `plan_aws_cost_attribution_reconciliation.md`.
- No CUR (Cost and Usage Report) migration.

---

## 3. Pipeline Compute — design

### 3.1 The good news
A classic pipeline (DLT) update runs on a normal Databricks cluster that **is
tagged `ClusterId`** on AWS. That cost is already sitting in
`dbspend360_cloud_cost_explorer` keyed by `cluster_id`. Staging keeps
`cluster_id`. So this is a **join, not a new ingest**.

Serverless pipelines (~96% of pipeline spend per the DLT plan) have **no
separate EC2 line** — the VM cost is embedded in the serverless DBU rate. The
correct value there is **not `$0` of real cost** but "cloud cost is not
separable" — surface it as a note, not a number (see §5).

**Serverless detection (corrected).** `compute_mode` is *not* keyed on
`cluster_id IS NULL` alone. Serverless Model Serving / Vector Search / AI
Functions endpoints carry a **non-null `-v2n`-style `cluster_id`** on serverless
SKUs, yet run in Databricks' own account (that `cluster_id` exists under **no
AWS tag**, so there is genuinely zero customer EC2). A row is therefore
`serverless` when **any** of: `cluster_id IS NULL`, a serverless-only
`billing_origin_product` (`MODEL_SERVING` / `VECTOR_SEARCH` / `AI_FUNCTIONS`),
or `sku_name LIKE '%SERVERLESS%'`. The flag is derived as a group-level
aggregate in staging (so it stays a function of the `(cluster_id,
billing_origin_product)` MERGE key), and `classic_staging` in the rollup is
filtered on `compute_mode = 'classic'` (not just `cluster_id IS NOT NULL`) so
these endpoints never enter the cloud attribution.

### 3.2 The subtlety: grain mismatch (must get right for accuracy)
- Cloud explorer grain: `(cluster_id, usage_date, currency)` — **no product
  dimension**.
- Rollup grain: `(pipeline_id, usage_date, billing_origin_product)` — **no
  `cluster_id`**.

If we naively joined cloud onto each staging row (which is per
`cluster × product`), a cluster that touched two `billing_origin_product`s on the
same day would get its EC2 cost **counted twice**. We must attribute each
cluster's cloud cost **once per `(cluster_id, day)`**.

**Recommended attribution (accurate + reconcilable):**
1. Build `cloud_df` = explorer filtered to the window, distinct on
   `(cluster_id, cost_incurred_date, currency)`.
2. From staging, build the **distinct** classic set
   `(workspace_id, pipeline_id, usage_date, cluster_id, currency)` where
   `cluster_id IS NOT NULL`.
3. **Assert** each `(cluster_id, usage_date)` maps to **≤1 pipeline** (DLT
   classic clusters are pipeline-scoped). If violated, fall back to a
   DBU-proportional split and log it — never silently double-count.
4. LEFT-join the distinct classic set to `cloud_df` → `cloud_cost` per
   `(pipeline_id, usage_date)`.
5. Distribute that pipeline-day cloud across the rollup's product rows
   proportional to each row's **classic** `databricks_cost` share, so:
   - `SUM(cloud_cost)` over a pipeline-day == the cluster cloud for that
     pipeline's clusters that day (exact at pipeline-day; product split is an
     informed apportionment, documented in the DDL note).
   - Serverless-only product rows receive `cloud_cost = 0` (correct).

> If you prefer zero apportionment ambiguity: attach the full pipeline-day cloud
> to the single product row with the largest classic DBU and set the others to
> `0`. The pipeline-day total is still exact; the per-product line is then
> "lumped" rather than "spread". Pick one and state it in the DDL comment.
> Recommendation: **proportional**, matching the all-purpose precedent.

### 3.3 Reconciliation invariant (mirror all-purpose §3.3)
Because the rollup drops `cluster_id`, assert reconciliation on the **intermediate
join** (before the product collapse), not on the final table:

> For every `(cluster_id, usage_date, currency)` in the classic join set,
> the cloud cost attributed to pipelines must equal
> `dbspend360_cloud_cost_explorer.cloud_cost` for the same key within `$0.01`.

Unmatched explorer clusters (job / all-purpose clusters) are expected and simply
not attributed to pipelines — they are **not** an error. Unmatched classic
staging clusters (a classic cluster with no explorer row yet) flow through with
`cloud_cost = 0` and feed the "data not present" note (§5).

### 3.4 Code touch points (Pipeline)
- `jobs/notebooks/pipeline_spends_app.ipynb` — fill the `TODO(v2)` slot with the
  §3.2 attribution + §3.3 assertion. Add `cloud_cost_table` to the client ctor /
  app wiring (it already exists in the all-purpose app — copy the pattern).
- `jobs/ddls/dbspend360_total_pipeline_spends.ipynb` — no column change
  (`cloud_cost` reserved); update the v1 doc note to v2.
- `jobs/resource_templates/DBSPEND360.yaml` — add
  `depends_on: cloud_cost_explorer` to the `pipeline_spends` task (today it only
  depends on the DBU task; it must wait for the explorer like `all_purpose_spends`
  does).
- `server/services/databricks_service.py` — pipeline functions: stop forcing
  `cloud_cost`/`total_cloud_cost` to `0`/`None`; `SELECT SUM(cloud_cost)` like
  the all-purpose functions.
- `server/routers/pipelines.py` + pipeline models — expose `cloud_cost` /
  `total_cloud_cost` (and `compute_mode`/`cost_basis` are already present).
- Frontend: `PipelinesTable.tsx` (add the `EC2 / EBS` column via `useCloudGate`),
  `PipelineSummaryCards.tsx` (add a cloud KPI; reword "v1: DBU only"),
  `PipelineDetailsModal.tsx`, `types/pipeline.ts`, regenerate the FastAPI client.

---

## 4. Instance Pools — design

### 4.1 Why the existing explorer can't help
The cluster explorer groups by `ClusterId`. **Idle/warm pool capacity has no
`ClusterId`** — it only carries `DatabricksInstancePoolId`. So idle pool cost,
which is the *primary reason to track pools at all*, is invisible to the current
pipeline. We need a **new CE query grouped by the pool tag**.

### 4.2 NEW data source
Add a second CE call inside `aws_cloud_cost_explorer_app.ipynb` (reuse the
credential / chunking / retry / pagination machinery in `AWSCostClient`):

```
GroupBy = [TAG DatabricksInstancePoolId, DIMENSION SERVICE]
Filter  = SERVICE IN ('Amazon Elastic Compute Cloud - Compute', 'EC2 - Other')
Metric  = AmortizedCost, Granularity = DAILY
```

Land it in a **new table** `dbspend360_pool_cloud_cost_explorer`:

```sql
CREATE TABLE IF NOT EXISTS ${catalog}.${schema}.dbspend360_pool_cloud_cost_explorer (
  instance_pool_id    STRING,
  cloud_cost          DOUBLE,
  compute_cost        DOUBLE,   -- NULL on AWS (single bucket)
  storage_cost        DOUBLE,   -- NULL on AWS
  network_cost        DOUBLE,   -- NULL on AWS
  other_cost          DOUBLE,   -- NULL on AWS
  currency            STRING,
  created_at          TIMESTAMP,
  updated_at          TIMESTAMP,
  cost_incurred_date  DATE
)
CLUSTER BY AUTO
```

Grain: **`(instance_pool_id, cost_incurred_date, currency)`**. Wrap the new CE
call in `try/except` so a pool-tag failure logs to `dbspend360_error_log` and
does **not** break the existing cluster explorer path or the DAG (same isolation
pattern as `plan_aws_cost_attribution_reconciliation.md` CP3).

> A dedicated table (not a new grouping column on `dbspend360_cloud_cost_explorer`)
> keeps the cluster explorer byte-stable and avoids a `(cluster_id,
> instance_pool_id)` composite-key migration on a table three other tabs depend
> on.

### 4.3 The accuracy question — RESOLVED by probe (2026-06-26)
**Do pool-backed instances also carry a `ClusterId` tag while a cluster is
attached?** Verified empirically by running the discovery CE query against
`e2-demo-field-eng` (service credential `dbspend-read-ce`), 14-day window
`2026-06-12 → 2026-06-26`:

```
get_tags(TagKey='DatabricksInstancePoolId')           -> 10 non-empty pool values (tag IS in billing)
GroupBy=[TAG DatabricksInstancePoolId, DIMENSION SERVICE], EC2 filter
  -> EC2-in-filter total = $13,840.58
     pool-tagged          = $1,206.09  (10 pools)
     untagged-by-pool     = $12,634.49 (job/all-purpose/SQL-warehouse compute)
GroupBy=[TAG DatabricksInstancePoolId, TAG ClusterId], EC2 filter
  -> pool-tagged split: idle(no ClusterId) = $1,206.09 | active(has ClusterId) = $0.00
```

Corroborated from the usage side via SQL: in the explorer's window
(`2026-03-18 → 2026-06-14`), of **1,613** pool-backed clusters only **4**
(`$110.27`) appear in `dbspend360_cloud_cost_explorer`.

**Outcome: Case B — strongly supported, with one caveat to close.** Pooled
instances are tagged with `DatabricksInstancePoolId` and, in the probe window,
were **not** tagged with `ClusterId` even while a cluster was actively borrowing
them. Caveat (must not be glossed): the two probes used **non-overlapping
windows** — the dual-tag CE `active = $0.00` is the **14-day** window
(`2026-06-12 → 2026-06-26`), while the `$110.27 / 4-cluster` overlap was found in
the **~3-month** SQL window (`2026-03-18 → 2026-06-14`). So the dual-tag `$0.00`
proves disjointness **only within those 14 days**, and the `$110.27` is direct
evidence that a small amount of pool-associated compute *did* carry `ClusterId`
historically. The correct reading is therefore **"essentially disjoint, with a
tiny (<$110/quarter) historical overlap"**, *not* "never / zero, decisively."
**Decision (chosen):** ship the **permanent `ClusterId` netting guard** in
consequence 2 below — it is robust regardless of window, so a full-window
re-probe is *optional* (nice-to-have, not a gate). Consequences for the design:

1. **The `DatabricksInstancePoolId` tag is present in AWS billing** → the pool
   cloud feature is feasible via the §4.2 CE pool-tag query.
2. **Near-zero double-counting — but add a guard, do not assume zero.** Pool EC2
   cost is overwhelmingly `ClusterId`-free, so almost none of it is in the
   existing cluster explorer; the new pool explorer is the *primary* home of pool
   EC2 cost. However, because the dual-tag probe only covered 14 days and the SQL
   found `$110.27` of pool-backed `ClusterId` cost over the quarter, the pool CE
   path **must net out any cost that also carries `ClusterId`** (run the §4.2
   query as a 3-tag/exclusion variant: `TAG DatabricksInstancePoolId` minus the
   `(pool, ClusterId)` intersection, or subtract the dual-tagged slice) rather
   than asserting "no de-dup logic required." With that guard the pool tab and
   the cluster/all-purpose/pipeline tabs do not overlap. (Cross-tab DBU overlap
   from `plan_instance_pools_tab.md` §3.6 still applies to DBU; cloud cost
   overlap is reduced to ~0 by the guard.)
3. **The dual-tag idle/active split does NOT work on this account.** Because
   active pooled instances also lack `ClusterId`, the dual-tag query labels
   100% of pool cost "idle" — it cannot distinguish genuine idle from active.
   So §4.5's idle/active split must use `system.compute.instance_events`
   (the v2b path), **not** the dual-tag trick.
4. **Pools are a small slice here** (~$86/day across 10 pools vs ~$900/day of
   non-pool EC2), but the pipeline must still be correct and self-monitoring.

Record this Case-B outcome in the DDL note and the README ("pool cloud cost is
disjoint from cluster cloud cost; tabs are additive, not overlapping, for EC2").

### 4.4 Join into the pool rollup (grain handling)
Pool cloud cost is **per pool-day**, but the rollup grain is
`(instance_pool_id, cluster_id, usage_date)`. If we attached pool-day cloud to
every cluster row it would be **multiplied by the number of clusters**. Attach it
**once per pool-day** — but the join direction is the trap (verified against
`dbspend360_pool_dbu_cost_app.ipynb`):

> **The `__pool_overhead__` row does not always exist.** That sentinel row is
> only produced when `system.billing.usage` has a pool-tagged row with
> `cluster_id IS NULL`. But **idle pool capacity emits zero `system.billing.usage`
> rows** (stated in §4.1 and in `pool_spends_app.ipynb`). So an **idle-only
> pool-day has no rollup row at all** — not even a `__pool_overhead__` row.
> Idle pools are *the whole point of the tab* (§4.1), so this is the common
> case, not an edge case. A plain "LEFT-join cloud onto the rollup" therefore
> silently **drops** the pool EC2 cost we most want, and the §4.6 invariant
> (`SUM(cloud_cost) per (pool,day,currency)` == explorer) would fail by exactly
> that amount.

Correct approach — **drive the join from the pool cloud table, not the rollup**:

- Build the attach set from `dbspend360_pool_cloud_cost_explorer` at
  `(instance_pool_id, cost_incurred_date, currency)` grain (its native grain).
- **FULL OUTER / union** it against the DBU-derived rollup rows on
  `(instance_pool_id, usage_date, currency)` so that:
  - pool-days **with DBU and with cloud** → cloud lands on the
    `__pool_overhead__` row (created if absent), `cloud_cost = 0` on per-cluster
    rows;
  - pool-days **with cloud but no DBU** (idle-only) → **synthesize** a new
    `(instance_pool_id, '__pool_overhead__', usage_date)` row carrying
    `databricks_cost = 0`, `cloud_cost = <pool cloud>`, so the cost is not lost
    and the MERGE key stays well-formed;
  - pool-days **with DBU but no cloud** → `cloud_cost = NULL` (the §5 "unknown"
    note), unchanged.
- Rationale: pool VM cost (especially idle) is **pool-level, not attributable to
  a specific attached cluster** — modeling it on the synthesized overhead row is
  the honest representation and makes `SUM(cloud_cost) GROUP BY pool, day` exact
  *including* idle-only days.
- `total_cost` recomputes automatically from the existing expression.
- Note the rollup MERGE key is `(instance_pool_id, cluster_id, usage_date)` with
  **no currency** today; if multi-currency pool cost ever appears, add `currency`
  to the key (the all-purpose path already does this — §1.4) to avoid the
  overhead-row colliding across currencies.

UI consequence: the pool → day → cluster drill-down shows EC2 cost at the **pool
and day** level; per-cluster rows show `—` with a tooltip "Pool VM cost is
tracked at the pool level, not per attached cluster (AWS tags pool instances with
`DatabricksInstancePoolId`, not `ClusterId`)."

### 4.5 Idle vs active split — must use `system.compute.instance_events` (v2b)
The §4.3 probe ruled out the dual-tag (`ClusterId`) split on this account: pooled
instances never carry `ClusterId`, so CE labels 100% of pool cost "idle" and
cannot separate genuine idle from active. The **"idle pool waste"** KPI — the
single most valuable number a pools tab can show — therefore needs a different
source:

- Read `system.compute.instance_events` (Public Preview), which carries
  `instance_pool_id` on every event. Derive per-instance `idle_minutes`
  (state `INSTANCE_READY`, no cluster attached) vs `active_minutes`
  (state `INSTANCE_PLACED`) from state transitions.
- Apply the **ratio** `idle_minutes / (idle+active)` to the **actual** pool EC2
  `cloud_cost` from `dbspend360_pool_cloud_cost_explorer` to split it into
  `idle_cloud_cost` / `active_cloud_cost`. This keeps the dollar total tied to
  real billed cost (not list price) while getting the split from events.
- Reserve `idle_cloud_cost` / `active_cloud_cost` columns on the pool explorer /
  rollup so adding this later is non-breaking.

**Recommendation:** ship §4.4 (accurate pool EC2 **total**) first; add the
events-based idle/active split as a fast follow. Both are independently
mergeable.

### 4.6 Reconciliation invariant (pools)
> For every `(instance_pool_id, usage_date, currency)`, `SUM(cloud_cost)` written
> to `dbspend360_total_pool_spends` must equal
> `dbspend360_pool_cloud_cost_explorer.cloud_cost` within `$0.01`.

Plus a post-write monitor mirroring the AWS explorer's `_monitor_post_write`:
if window pool `cloud_cost` collapses to ~0 while pool DBU is non-zero, raise a
non-silent alarm (suspected pool-tag lapse).

### 4.7 Code touch points (Instance Pools)
- `jobs/notebooks/aws_cloud_cost_explorer_app.ipynb` — add the pool-tag CE call +
  MERGE into the new table (isolated `try/except`).
- `jobs/ddls/dbspend360_pool_cloud_cost_explorer.ipynb` — **new DDL**; add to
  `jobs/ddls/create_all_tables.ipynb`.
- `jobs/notebooks/pool_spends_app.ipynb` — fill the `TODO(v2)` slot per §4.4 +
  §4.6; add `pool_cloud_cost_table` to ctor/app wiring.
- `jobs/resource_templates/DBSPEND360.yaml` — `pool_spends` already
  `depends_on: Dbspend360_pool_dbu_costs`; that task already depends on
  `cloud_cost_explorer`, so the new pool table (written in the explorer task) is
  available. Confirm ordering holds after edits.
- `server/services/databricks_service.py` — instance-pool functions: stop
  forcing `cloud_cost`/`total_cloud_cost` to `None`; sum real values.
- `server/routers/instance_pools.py` + models — expose `cloud_cost` /
  `total_cloud_cost`.
- Frontend: `InstancePoolsTable.tsx` (add `EC2 / EBS` column via `useCloudGate`),
  `InstancePoolsSummaryCards.tsx` (cloud KPI; idle-waste KPI if §4.5;
  reword "v1: DBU only"), `InstancePoolsDashboard.tsx` (remove the v1
  disclaimer), `InstancePoolDetailsModal.tsx`, `types/instance-pool.ts`,
  regenerate the FastAPI client. Update the LLM `/analyze` prompt to drop the
  "DBU-only" caveat.

---

## 5. "Data not present" — explicit, specific notes (a stated requirement)

Never render a misleading bare `$0`. Use a typed reason so the UI shows the right
note. Proposed rules:

| Situation | Cell value | Note / tooltip |
|---|---|---|
| Pipeline **serverless** row (`compute_mode=serverless`) | `—` (not `$0`) | "Serverless — EC2 cost is bundled into the serverless DBU rate; no separate VM line." |
| Pipeline **mixed** row | EC2 of the classic portion + badge | "Classic portion only; serverless portion has no separate VM line." (`cost_basis=partial` already encodes this) |
| Pipeline **classic** row, no matching explorer cluster/day | `—` | "EC2 cost not yet available for this cluster/day (Cost Explorer lag or untagged cluster)." |
| Pool-day with no pool-tag cloud row | `—` | "Pool VM cost unavailable — confirm the `DatabricksInstancePoolId` tag is enabled and Cost Explorer has caught up." |
| Per-cluster row inside a pool drill-down | `—` | "Pool VM cost is tracked at the pool level, not per attached cluster." |
| Date before the pool-explorer cutover | `—` | "Pool EC2 tracking started YYYY-MM-DD." |

Implementation: the notebooks should distinguish **"0 known"** from **"unknown"**.
Easiest robust approach — keep `cloud_cost` as `NULL` when unknown and `0.0` only
when genuinely zero; the LEFT joins already produce `NULL` on no-match, and the
existing `COALESCE(cloud_cost,0)` in `total_cost` keeps totals safe. The UI then
renders `NULL → "—" + note` and `0.0 → "$0.00"`.

> Note this is a small but real refinement vs. the all-purpose pipeline, which
> coalesces cloud to `0.0` at write time. For these two tabs, preserving `NULL`
> is what lets the UI tell "we know it's zero" from "we don't have it yet".

---

## 6. Sequencing (each step independently mergeable)

1. **CP1 — Pipeline cloud join (data). ✅ DONE.** `pipeline_spends_app.ipynb`
   fills the `TODO(v2)` slot with the §3.2 DBU-weighted attribution (distinct
   `cloud_df` on `(cluster_id, usage_date, currency)`, attribute once per
   cluster-day, spread across product rows by classic DBU share) and the §3.3
   `_assert_reconciliation` (±0.01, writes mismatches to `dbspend360_error_log`).
   `DBSPEND360.yaml` `pipeline_spends` now `depends_on` both
   `Dbspend360_pipeline_dbu_costs` and `cloud_cost_explorer`. The
   `dbspend360_total_pipeline_spends` DDL note is updated v1→v2. Backfill window
   via `overlap_days`.
2. **CP2 — Pipeline service + API + client. ✅ DONE.** Flipped `None`→real in
   the four pipeline read functions (`get_pipelines_grouped`,
   `_get_batch_pipeline_days`, `get_top_pipelines`, `get_pipeline_summary_metrics`)
   plus `get_pipeline_cost_summary` (LLM feed): each now `SUM(cloud_cost)` and
   surfaces it, preserving `NULL` for fully-serverless rows (decision #3 / §5)
   rather than coalescing to `$0`. Models already reserved the optional
   `cloud_cost` / `total_cloud_cost` fields and the router passes them through,
   so exposing the fields + regenerating the FastAPI TS client completes the
   API surface. Pipeline LLM prompt left unchanged (cost_basis caveat still
   valid; not a CP2 touch point per §3.4).
3. **CP3 — Pipeline UI. ✅ DONE.** `PipelinesTable.tsx` adds the platform-aware
   `EC2 / EBS` column (`useIsAws` / `AWS_CLOUD_LABEL`) rendering `—` + note for
   `NULL` (serverless); `PipelineSummaryCards.tsx` adds the cloud KPI and rewords
   the "v1: DBU only" headline; `PipelineDetailsModal.tsx` repoints the DBU-only
   caveat at the new column. Verify against live data.
4. **CP4 — Pool probe. ✅ DONE (2026-06-26), one follow-up open.** Case B
   strongly supported (§4.3): pool tag present in billing; no `ClusterId` on
   pooled instances *in the 14-day probe window*; overlap reduced to a tiny
   historical `$110.27` (see §4.3 caveat). Follow-up before trusting totals:
   either re-probe the dual-tag query over the full ingest window **or** keep the
   §4.3-#2 `ClusterId` netting guard. Idle/active split deferred to
   `instance_events`.
5. **CP5 — Pool explorer (data). ✅ DONE.** `aws_cloud_cost_explorer_app.ipynb`
   adds the pool-tag CE call (`_build_pool_ce_params`, dual TAG
   `DatabricksInstancePoolId`+`ClusterId`) with the §4.3 `ClusterId` netting
   guard in `_parse_pool_response` (keeps only ClusterId-free rows), an isolated
   `try/except` that logs to `dbspend360_error_log` and never breaks the DAG,
   `merge_pool_cloud_cost_explorer` + schema/negative/currency validations +
   audit logging, and the §4.6 `_monitor_pool_post_write` alarm. New DDL
   `jobs/ddls/dbspend360_pool_cloud_cost_explorer.ipynb` (§4.2 grain, plus
   reserved `idle_cloud_cost`/`active_cloud_cost` for §4.5) is registered in
   `create_all_tables.ipynb`.
6. **CP6 — Pool rollup join. ✅ DONE.** `pool_spends_app.ipynb` fills the
   `TODO(v2)` slot per §4.4/§4.6: reads `dbspend360_pool_cloud_cost_explorer`,
   drives the join FROM the cloud table (collapses to `(pool, day)`, sums
   currency with a multi-currency warning), and **synthesizes
   `__pool_overhead__` rows** (`databricks_cost = 0`) for pool-days that have
   cloud but no existing overhead row (idle-only days included) via a
   `left_anti` against existing overhead keys. Cloud lands on the overhead row
   only; per-cluster rows keep `cloud_cost = NULL` (§5 "—" note). The
   empty-window short-circuit now requires BOTH DBU and cloud empty (so
   idle-only cloud is no longer dropped). `_assert_reconciliation` enforces the
   §4.6 `(pool, day)` invariant (±0.01, FULL OUTER, writes mismatches to
   `dbspend360_error_log`) on the pre-MERGE source; `_monitor_post_write` adds
   the advisory cloud~0/DBU>0 alarm. Ctor/app wired with `pool_cloud_cost_table`;
   DDL note updated v1→v2. DAB ordering already correct (`pool_spends` →
   `Dbspend360_pool_dbu_costs` → `cloud_cost_explorer`), no YAML change.
7. **CP7 — Pool service + API + client. ✅ DONE.** All five pool service
   functions (`get_instance_pool_summary_metrics`, `get_instance_pools_grouped`,
   `_get_batch_pool_days_and_clusters`, `get_top_instance_pools`,
   `get_instance_pool_details`) now `SUM(cloud_cost)` preserving NULL and
   surface a `total_cloud_cost` field; the regenerated FastAPI TypeScript
   client carries the field on the pool models, and `cp7_smoke.py` covers the
   read path (verified in `server/services/databricks_service.py`,
   `server/routers/instance_pools.py`, the regenerated client, and
   `claude_scripts/cp7_smoke.py`).
8. **CP8 — Pool UI. ✅ DONE.** `InstancePoolsTable.tsx` adds the platform-aware
   `EC2 / EBS` column (`useIsAws` / `AWS_CLOUD_LABEL`) at the pool and per-day
   grain via `PoolCloudCostCell` (real `$`, or `—` + typed note when the
   pool-tag cloud row hasn't landed — plan §5); per-cluster drill-down rows
   render `—` with the "tracked at the pool level, not per attached cluster"
   tooltip (`PerClusterCloudCell`). Notes centralized in new
   `client/src/lib/pool-display.ts`. `InstancePoolsSummaryCards.tsx` swaps the
   "Total DBU Spend" headline for **Total Spend** (DBU + EC2/EBS) and adds a
   dedicated EC2/EBS KPI (`—` + note when `total_cloud_cost` is NULL).
   `InstancePoolsDashboard.tsx` drops the "v1 surfaces DBU cost only"
   disclaimer. The pool LLM prompt (`INSTANCE_POOL_ANALYSIS_PROMPT`),
   user-message, and structured fallback replace the old "DBU-only" caveat
   with the `POOL_IDLE_SPLIT_CAVEAT` ("the idle-vs-active VM cost split is not
   available yet" — §4.5) and now feed the real EC2/EBS cost into the cost
   summary. Type/router/model docstrings and `cp7_smoke.py` updated to match.
9. **CP9 — Reconciliation + monitors + README. ✅ DONE.** The per-key
   reconciliation invariants (`_assert_reconciliation`, ±0.01 → `dbspend360_error_log`)
   and post-write monitors (`_monitor_post_write` / `_monitor_pool_post_write`,
   cloud~0/DBU>0 alarm) were landed with CP1/CP5/CP6 and are verified present in
   `pipeline_spends_app.ipynb`, `pool_spends_app.ipynb`, and
   `aws_cloud_cost_explorer_app.ipynb`. The Case-B disjointness note is recorded
   in both pool DDLs. CP9 finalizes the **README**: the deployment section now
   lists all 13 tables and the four parallel job branches (Job Clusters,
   All-Purpose, Instance Pools, Pipeline Compute), and a new "**Cost attribution
   across tabs (and why they don't sum to the AWS bill)**" section documents the
   intentional DBU overlap, the disjoint EC2 explorers (cluster vs pool tag +
   `ClusterId` netting guard → additive, not overlapping), the shared-infra gap,
   the `—`/note honesty rules, and the reconciliation/monitor/audit machinery.

CP1–CP3 (pipeline) deliver value first and carry low risk (no new ingest).
CP4–CP9 (pools) are the larger, riskier half gated on the probe.

**Progress: CP1–CP9 ✅ DONE.** The pipeline half (CP1–CP3) is
fully shipped, the pool data path (CP4 probe + CP5 explorer/table + CP6 rollup
join) is in place, the pool read path is live end-to-end (CP7 service/API/client
+ CP8 pool UI), and CP9 documented the cross-tab overlap / reconciliation in the
README. **Plan complete.**

---

## 7. Acceptance criteria

- Pipeline classic rows show non-zero EC2 that reconciles to
  `dbspend360_cloud_cost_explorer` per `(cluster_id, day, currency)` within
  `$0.01`; serverless rows show `—` + note, never a misleading `$0`.
- Instance Pools show pool EC2 cost; `SUM(cloud_cost)` per `(pool, day, currency)`
  equals `dbspend360_pool_cloud_cost_explorer` within `$0.01`; idle-vs-active
  split present if Case A.
- No within-table double counting (the §3.2 grain fix and §4.4 once-per-pool-day
  attribution both hold under test).
- Every "missing data" path renders a specific note (§5), verified in the UI.
- README documents that pool/pipeline/cluster tabs intentionally overlap and do
  not sum to the AWS bill.

## 8. Key risks

- **Pool tag not actually applied on the account.** The whole pool path depends
  on `DatabricksInstancePoolId` reaching AWS billing tags. The §4.3 probe is the
  gate; if absent, fall back to the `system.compute.instance_events` list-price
  estimate (`plan_instance_pools_tab.md` §13 v2b) and label it an estimate.
- **Cross-tab double counting misread as a bug.** Mitigated by README + tooltips;
  this is the same already-accepted behavior as DBU.
- **CE cost/latency.** A second daily CE query doubles CE calls; chunking + the
  existing retry/backoff already handle CE rate limits.
- **Pipeline product-apportionment** of cloud is an informed split, not a tagged
  fact — documented in the DDL note; the pipeline-day total stays exact.

## 9. Decisions (all resolved 2026-06-26)

1. ~~Pipeline per-product cloud attribution: proportional vs. lump.~~
   **Resolved: proportional** — distribute pipeline-day cloud across product rows
   by each row's classic `databricks_cost` share, matching the all-purpose
   precedent (§3.2). Pipeline-day total stays exact; per-product line is an
   informed apportionment, documented in the DDL note.
2. ~~Pools first cut: total vs idle/active split.~~ **Resolved by CP4:** ship
   **total cloud only** first; idle/active split is a fast follow via
   `system.compute.instance_events` (the dual-tag split is impossible here).
3. ~~Keep `cloud_cost = NULL` for "unknown" vs. coalesce to `0.0`.~~
   **Resolved: keep `NULL` for "unknown", `0.0` only for genuine zero** — the
   LEFT/OUTER joins already produce `NULL` on no-match; `total_cost`'s existing
   `COALESCE(cloud_cost,0)` keeps totals safe, and the UI renders
   `NULL → "—" + note` vs `0.0 → "$0.00"` (§5).
4. ~~Pool/cluster double-count caveat (§4.3).~~ **Resolved: permanent `ClusterId`
   netting guard** in the pool CE path (§4.3-#2); full-window re-probe is optional.
5. ~~Pool rollup join shape for idle-only days (§4.4).~~ **Resolved: drive the
   join from the pool cloud table (FULL OUTER/union) and synthesize
   `__pool_overhead__` rows** for pool-days with cloud but no DBU, so idle pool
   EC2 is captured and §4.6 reconciles.

> **Status: CP1–CP9 implemented (verified 2026-06-26). Plan complete.**
> Pipeline half (CP1–CP3) fully shipped — notebook attribution + reconciliation,
> DAB dependency, service/API/client, and UI. Pool path fully shipped — CP4
> probe + CP5 explorer CE call + new DDL + `create_all_tables` + CP6 rollup
> join with overhead-row synthesis/§4.6 reconciliation + CP7 service/API/client
> + CP8 pool UI (EC2/EBS column + KPI, dropped v1 disclaimer, idle-split LLM
> caveat). CP9 finalized README cross-tab overlap / reconciliation docs and
> confirmed the reconciliation invariants + post-write monitors are in place.
