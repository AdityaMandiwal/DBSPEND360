# Plan — AWS cost attribution reconciliation (per-cluster + workspace-shared + workspace-total)

Branch (proposed): `feat/aws-cost-reconciliation`

## 1. Goal

DBSpend360's per-cluster cost breakdown looks structurally different between
AWS and Azure because of how the two clouds propagate tags. Azure ARM
auto-propagates `clusterid` to VMs, disks, NICs, public IPs, and bandwidth
meters, so per-cluster `compute / storage / network / other` populate cleanly.
AWS only writes `ClusterId` onto EC2 instances (EBS volumes inherit via
attachment). Everything else — NAT, S3, ELB, VPC endpoints, AWS Data Transfer
— is workspace-level shared infrastructure and never gets a per-cluster tag.

`utils_common.filter_valid_cost_rows` silently drops every untagged row before
the MERGE into `dbspend360_cloud_cost_explorer`, so on AWS the dashboard's
"Total Cloud Cost" undercounts the AWS console total by roughly 15–30%. The
shared cost is not just unattributed — it's invisible.

Goal of this work: surface the shared/untagged bucket honestly without
distorting the existing per-cluster pipeline, and add a reconciliation tile
that answers the question "does what DBSpend360 shows match my AWS bill?".

After this change the AWS dashboard has:

1. The existing per-cluster card, collapsed to a clean two-row Cloud /
   Databricks view (since storage / network / other are structurally always
   empty per-cluster on AWS).
2. A new **Workspace-shared (untagged)** card showing the multi-segment
   breakdown of cluster-unattributable AWS spend (NAT, S3, VPC endpoints,
   inter-AZ data transfer, etc.).
3. A new **Account reconciliation** card showing
   `per_cluster + workspace_shared ≈ workspace_total`, with a residual badge
   and threshold-colored status.

Azure and GCP are not touched. Their per-cluster card keeps its existing
4-segment view; they get no shared / reconciliation cards.

## 2. Non-goals

- **No changes to the Azure or GCP ETL.** `azure_cloud_cost_explorer_app.ipynb`
  and `gcp_cloud_cost_explorer_app.ipynb` are byte-identical after this PR.
- **No proportional allocation of shared infra back to clusters.** Defensible
  for chargeback, but it's a model not attribution. Out of scope.
- **No switch to AWS Cost and Usage Reports (CUR).** Multi-week build. Defer
  unless customers push back; IAM policy already reserves the permissions
  (`release/AWS Credentials and Permissions Setup.md`).
- **No SQL Warehouse cost surfacing.** The 2 untagged EC2-Compute rows we see
  per day are almost certainly SQL Warehouses (they tag with `WarehouseId`,
  not `ClusterId`). Surfacing them needs a parallel CE query with
  `GroupBy = TAG WarehouseId + DIMENSION SERVICE` and a new
  `dbspend360_warehouse_costs` table. Logged as v2 follow-up.
- **No schema change to `dbspend360_cloud_cost_explorer`.** The four segment
  columns stay nullable; the AWS path just stops populating storage / network /
  other. Azure continues to populate them.
- **No new top-level tab.** All new UI lives below the existing summary cards
  on the Job Clusters tab.

## 3. Confirmed decisions

The architectural forks below are **locked in**. They incorporate the
corrections from the design-review pass that preceded this plan
(see §10, "Resolved design issues").

| Fork | Decision | Detail in |
|---|---|---|
| Shared-cost table | **Reuse `dbspend360_other_cost_breakdown`** with `scope` column (`per_cluster` \| `workspace_shared`). No new `dbspend360_workspace_shared_costs` table. | §4.1, CP2 |
| Workspace-total table | **New `dbspend360_workspace_total_costs`** (date, total_cost, currency, cloud_provider). One row per day per cloud. Cloud-agnostic from day one. | §4.2, CP4 |
| Workspace-total CE filter | **Same SERVICE filter as the per-cluster call** (option 2b). Reconciles apples-to-apples. Avoids residual contamination from non-Databricks workloads in shared AWS accounts. | §10.4, CP4 |
| AWS segment null-out | **Null `storage_cost / network_cost / other_cost` AFTER `cloud_cost` is computed by `aggregate_costs_by_category`, then short-circuit `compute_quality_metrics` for AWS** so coverage trend isn't silently 100%. | §10.1, CP3 |
| `hasSegmented` gating | **Make `hasSegmented` cloud-aware in `SummaryCards.tsx`** (`metrics.total_compute_cost != null && cloudConfig?.platform !== 'AWS'`). Cleaner than nulling `compute_cost` and losing the per-cluster compute breakdown elsewhere. | §10.2, CP6 |
| Cascade audit | **Explicit audit checkpoint** (CP7) walks every consumer of `total_storage_cost / total_network_cost / total_other_cost` and confirms `$0.00` rows don't render for AWS. | §10.3, CP7 |
| Reconciliation thresholds | **3% green / 3–10% amber / >10% red**, with an absolute floor (residual < $50 always green). Matches CE AmortizedCost drift vs. invoice. | §10.5, CP9 |
| DAB task isolation | **New CE call and shared-bucket write wrapped in try/except** inside the existing `cloud_cost_explorer` notebook. Failure is logged to `dbspend360_error_log`, does not fail the task, does not break downstream DAG. | §10.6, CP3, CP4 |
| Backfill on first deploy | **Backfill 90 days into both new data surfaces** on first run after deploy. Gated by absence of any rows in `dbspend360_workspace_total_costs`. | §10.7, CP10 |
| Sequencing | 10 sequential checkpoints, each independently mergeable and reversible. See §6. | §6 |

## 4. Architecture overview

### 4.1 `dbspend360_other_cost_breakdown` — extended in place

Current schema:

```
cost_incurred_date DATE, cluster_id STRING, source_system STRING,
service_name STRING, cost DOUBLE, currency STRING,
created_at TIMESTAMP, updated_at TIMESTAMP
```

New column (additive, nullable, default `'per_cluster'` for backwards compat):

```
scope STRING  -- 'per_cluster' | 'workspace_shared'
```

- `scope = 'per_cluster'`: existing rows, where a cluster_id IS the
  attribution target and the row landed in 'other' because the service
  wasn't in `AWS_SERVICE_CATEGORIES`.
- `scope = 'workspace_shared'`: new rows from this PR, where the source row
  had no cluster_id at all. `cluster_id` column is set to the sentinel
  `'__workspace_shared__'` (never null, so existing MERGE key composition
  still functions).
- Add `category STRING` column too so the shared rows preserve their
  compute/storage/network classification (per-cluster rows always have
  `category='other'` so back-fill is a literal).

Merge key extended to
`(cost_incurred_date, cluster_id, source_system, service_name, currency, scope)`
so per-cluster and workspace-shared rows can't collide.

### 4.2 `dbspend360_workspace_total_costs` — new

```
cost_incurred_date DATE,
total_cost         DOUBLE,
currency           STRING,
cloud_provider     STRING,  -- 'AWS' | 'AZURE' | 'GCP'
created_at         TIMESTAMP,
updated_at         TIMESTAMP
PK (cost_incurred_date, cloud_provider, currency)
```

Populated only by the AWS notebook in this PR; Azure and GCP notebooks remain
untouched (their `cloud_provider` rows will simply never exist). UI handles
absence as "reconciliation tile hidden".

### 4.3 ETL flow (AWS only)

```
CE response (dual GroupBy: TAG ClusterId + DIMENSION SERVICE)
        │
        ▼
    spark_df
        │
        ├── filter cluster_id IS NOT NULL/'' ──► tagged_df ──► existing classified+aggregated path
        │                                                          │
        │                                                          ├── null storage/network/other
        │                                                          ├── MERGE into dbspend360_cloud_cost_explorer (unchanged contract)
        │                                                          └── write per-cluster 'other' rows to breakdown (scope='per_cluster')
        │
        └── filter cluster_id IS NULL/'' ─────► untagged_df ──► classify with build_aws_category_column
                                                                   │
                                                                   └── MERGE into breakdown (scope='workspace_shared',
                                                                                              cluster_id='__workspace_shared__')

(separate CE call, no GroupBy, same SERVICE filter)
        │
        ▼
    workspace_total_df ──► MERGE into dbspend360_workspace_total_costs
```

All three writes are wrapped in try/except so a single CE failure cannot
break the DAG.

### 4.4 API surface

Single new endpoint powers both new UI cards:

```
GET /api/cloud-reconciliation?from_date=YYYY-MM-DD&to_date=YYYY-MM-DD
```

Returns `null` (or `{ cloud_provider: "AZURE", available: false }`) when
`cloud_platform != AWS` so the contract stays simple and the frontend can
short-circuit without conditional fetching.

For AWS the response includes:
- `per_cluster_total`, `workspace_shared_total`, `workspace_total_cloud`,
  `residual`, `residual_pct`
- `shared_breakdown`: {compute, storage, network, other}
- `shared_services`: ranked list of (service_name, category, cost)

### 4.5 UI

Two new platform-gated cards added to `JobClustersDashboard.tsx`, in a single
new row below the existing `SummaryCards`:

- `WorkspaceSharedCostCard.tsx` (left): category bar + click-to-expand
  service list, styled like `OtherCostBreakdownModal.tsx`.
- `AccountReconciliationCard.tsx` (right): three-number tile with a
  threshold-colored residual badge.

Both hide entirely when `cloudConfig?.platform !== 'AWS'`. Plus a one-line
edit to `SummaryCards.tsx` to make `hasSegmented` platform-aware, which
collapses the per-cluster card to the existing two-row fallback view for AWS
without any segment row showing `$0.00`.

## 5. Repo touchpoints

| File | Change | Checkpoint |
|---|---|---|
| `jobs/ddls/dbspend360_other_cost_breakdown.ipynb` | ADD COLUMNS `scope STRING DEFAULT 'per_cluster'`, `category STRING DEFAULT 'other'` | CP2 |
| `jobs/ddls/dbspend360_workspace_total_costs.ipynb` | NEW FILE | CP4 |
| `jobs/notebooks/utils_common.ipynb` | New `merge_other_cost_breakdown_v2` accepting `scope`; deprecation comment on existing fn. Existing fn still works for Azure / GCP via default `scope='per_cluster'`. | CP2 |
| `jobs/notebooks/aws_cloud_cost_explorer_app.ipynb` | Branch tagged/untagged; new `get_workspace_total_daily` CE method; new `write_workspace_shared_costs`; new `compute_and_log_residual`; null-out storage/network/other AFTER aggregate; skip coverage logging for AWS | CP1, CP3, CP4 |
| `jobs/resource_templates/DBSPEND360.yaml` | No change. New writes happen inside the existing `cloud_cost_explorer` task. | — |
| `server/config/config_loader.py` | Add `workspace_total_table_name` property (defaults to `<schema>.dbspend360_workspace_total_costs`) | CP5 |
| `server/services/databricks_service.py` | New `get_cloud_reconciliation(from_date, to_date)` method | CP5 |
| `server/routers/dashboard.py` | New `GET /api/cloud-reconciliation` endpoint | CP5 |
| `server/models/job_spend.py` | New `CloudReconciliationResponse` model | CP5 |
| `client/src/components/SummaryCards.tsx` | One-line change to `hasSegmented` (platform-aware) | CP6 |
| `client/src/components/WorkspaceSharedCostCard.tsx` | NEW FILE | CP7 |
| `client/src/components/AccountReconciliationCard.tsx` | NEW FILE | CP8 |
| `client/src/components/JobClustersDashboard.tsx` | Layout integration of two new cards | CP9 |
| `client/src/hooks/useJobSpends.ts` | New `useCloudReconciliation(dateRange)` hook | CP7 |
| `release/AWS Credentials and Permissions Setup.md` | Note that the no-Filter (now SERVICE-filtered) CE call uses the same `ce:GetCostAndUsage` permission already in the policy — no IAM change required | CP10 |

## 6. Checkpoints (sequential, each independently mergeable)

Each checkpoint is a self-contained PR-shaped unit of work. After each, the
app is fully shippable and reversible — a CP can be reverted without
cascading rollbacks of earlier ones. The "Acceptance" line is what the next
CP starts from.

### CP1 — AWS notebook: branch tagged/untagged (no behavior change yet)

**Touches:** `jobs/notebooks/aws_cloud_cost_explorer_app.ipynb` (Cell 6,
`AWSCostReporterApp.run`).

In `run()`, before the existing `filter_valid_cost_rows` call, split:

```python
tagged_df   = spark_df.filter((F.col("cluster_id").isNotNull()) & (F.col("cluster_id") != ""))
untagged_df = spark_df.filter((F.col("cluster_id").isNull())   | (F.col("cluster_id") == ""))
```

Tagged path is the existing flow, untouched. `untagged_df` is computed and
its row count logged via `self.logger.info`, but **not written anywhere**.

**Acceptance:**
- `dbspend360_cloud_cost_explorer` row counts byte-identical to pre-CP1 for
  the same date window.
- Audit log entry includes a new `untagged_rows=N` token in `quality_msg`.

**Why first:** pure refactor, zero behavior change, gives us a hook for CP3
to plug the new write into.

**Rollback:** revert the notebook cell.

---

### CP2 — Extend `dbspend360_other_cost_breakdown` schema

**Touches:** `jobs/ddls/dbspend360_other_cost_breakdown.ipynb`,
`jobs/notebooks/utils_common.ipynb`.

DDL adds two columns (both additive, nullable, with literal defaults for
back-fill safety):

```sql
ALTER TABLE ${catalog}.${schema}.dbspend360_other_cost_breakdown
  ADD COLUMNS (
    scope    STRING,
    category STRING
  );

UPDATE ${catalog}.${schema}.dbspend360_other_cost_breakdown
   SET scope    = COALESCE(scope, 'per_cluster'),
       category = COALESCE(category, 'other')
 WHERE scope IS NULL OR category IS NULL;
```

In `utils_common`, add a new function `merge_other_cost_breakdown_v2` that
accepts a `scope` column on the source DataFrame and extends the merge key
to include `scope`. Keep `merge_other_cost_breakdown` as a thin wrapper that
calls v2 with `scope='per_cluster'` so Azure / GCP notebooks don't need
edits.

**Acceptance:**
- DDL run on dev schema succeeds; existing rows have
  `scope='per_cluster', category='other'`.
- Running the Azure notebook end-to-end after the change produces no schema
  errors and writes rows with `scope='per_cluster'`.

**Why now:** unblocks CP3 without coupling to the AWS-specific write logic.

**Rollback:** Delta supports column drop on a managed table; or simply ignore
the new columns (defaults make them invisible to existing consumers).

---

### CP3 — AWS notebook: write untagged rows to breakdown + null structurally-empty segments

**Touches:** `jobs/notebooks/aws_cloud_cost_explorer_app.ipynb`.

Two changes, both wrapped in try/except so failure logs to
`dbspend360_error_log` and does not fail the parent task:

**3a. Untagged-rows write path:**

```python
try:
    untagged_classified = (
        untagged_df
        .withColumn("category", build_aws_category_column())
        .withColumn("cluster_id", F.lit("__workspace_shared__"))
        .withColumn("scope", F.lit("workspace_shared"))
    )
    shared_agg = (
        untagged_classified
        .groupBy("cluster_id", "service_name", "category", "currency",
                 "cost_incurred_date", "scope")
        .agg(F.sum("cost").alias("cost"))
        .withColumn("source_system", F.lit("AWS"))
    )
    merge_other_cost_breakdown_v2(self.breakdown_table, shared_agg)
except Exception as e:
    self.logger.warning(f"Workspace-shared write failed: {e}")
    write_error_log_entries([str(e)[:500]], "AWS", "WORKSPACE_SHARED_WRITE_FAILED",
                            self.error_log_table)
```

**3b. Null structurally-empty segments on tagged path:**

In the tagged-path block, **after** `aggregate_costs_by_category` has
computed `cloud_cost` from the four segments and **after**
`compute_quality_metrics` has captured the audit message (but only if
non-AWS — see 3c), but **before** `merge_cloud_cost_explorer`:

```python
agg_df = (agg_df
    .withColumn("storage_cost", F.lit(None).cast("double"))
    .withColumn("network_cost", F.lit(None).cast("double"))
    .withColumn("other_cost",   F.lit(None).cast("double")))
```

Ordering matters: `cloud_cost` is preserved because it was computed in the
prior step; `compute_cost` stays populated so per-cluster compute breakdown
is still queryable from downstream tables.

**3c. Skip coverage logging for AWS:**

`compute_quality_metrics` currently writes
`classification_coverage=XX.X%` to the audit message, which
`CoverageTrendChart` parses. After the null-out, AWS coverage would be a
trivially-true 100% (no `other_cost` to be "unclassified"). Replace the call
with:

```python
quality_msg = f"overlap_days={self.overlap_days}, rows={merged_row_count}, classification_coverage=N/A"
```

…and update `get_classification_coverage_trend` in `databricks_service.py`
to skip `N/A` entries via the existing regex (no DB change needed — the
regex `'classification_coverage=([0-9.]+)%'` already won't match `N/A`).

**Acceptance:**
- `dbspend360_other_cost_breakdown` contains rows with
  `cluster_id='__workspace_shared__'`, `scope='workspace_shared'` after a
  run on a 2-day window that includes known untagged spend.
- `dbspend360_cloud_cost_explorer` AWS rows have
  `storage_cost = network_cost = other_cost = NULL` and `cloud_cost` is
  unchanged from a control run.
- `CoverageTrendChart` shows no new AWS data points (existing pre-CP3
  points remain).
- Inducing a failure in 3a (e.g. wrong table name) logs to
  `dbspend360_error_log` and the rest of the run completes successfully.

**Rollback:** revert the notebook cell. The breakdown rows are
self-isolating (scope filter); the cloud_cost rows are written with NULLs
that future runs will keep writing as NULLs until rollback.

---

### CP4 — AWS notebook: workspace-total CE call + new DDL

**Touches:** `jobs/notebooks/aws_cloud_cost_explorer_app.ipynb`,
`jobs/ddls/dbspend360_workspace_total_costs.ipynb` (new),
`jobs/ddls/create_all_tables.ipynb` (wire the new DDL).

**4a. New DDL file** modeled on existing patterns (widget for catalog/schema,
CLUSTER BY AUTO, exit with FQN).

**4b. New `AWSCostClient.get_workspace_total_daily(start, end)` method:**

Same TimePeriod and SERVICE filter as the existing call, Granularity=DAILY,
NO GroupBy. Returns one row per day per currency.

**4c. New `compute_and_log_residual()` method on `AWSCostReporterApp`:**

```python
try:
    workspace_total_df = self.client.get_workspace_total_daily(start_dt, end_dt)
    merge_workspace_total(self.workspace_total_table, workspace_total_df, "AWS")

    residual_pct = self._compute_residual_pct(start_dt, end_dt)
    if abs(residual_pct) > 0.05:
        write_error_log_entries(
            [f"AWS reconciliation drift {residual_pct:.1%} for {start_dt} → {end_dt}"],
            "AWS", "RECONCILIATION_DRIFT", self.error_log_table,
        )
except Exception as e:
    self.logger.warning(f"Workspace-total write failed: {e}")
    write_error_log_entries([str(e)[:500]], "AWS", "WORKSPACE_TOTAL_WRITE_FAILED",
                            self.error_log_table)
```

`merge_workspace_total` lives in `utils_common` (new).

**Acceptance:**
- `dbspend360_workspace_total_costs` has one row per day for the run window
  with `cloud_provider='AWS'`.
- A `RECONCILIATION_DRIFT` row appears in `dbspend360_error_log` if and only
  if the residual exceeds 5%.
- Inducing a CE failure (e.g. bad credential) logs the failure and the rest
  of the run completes.

**Rollback:** revert the notebook cells. The DDL table can stay (orphan data
costs zero); the new utility is dead code until re-introduced.

---

### CP5 — Backend: config + service + endpoint

**Touches:** `server/config/config_loader.py`,
`server/services/databricks_service.py`, `server/routers/dashboard.py`,
`server/models/job_spend.py`.

- `AppConfig.workspace_total_table_name` property, derived from
  `schema_name` (mirrors `all_purpose_table_name`).
- `DatabricksService.get_cloud_reconciliation(from_date, to_date)` runs
  three short queries (cloud cost explorer SUM, breakdown SUM with
  scope='workspace_shared' grouped by category and by service, workspace
  total SUM). Returns `None` if `cloud_platform != AWS`.
- `GET /api/cloud-reconciliation` endpoint, returning
  `CloudReconciliationResponse | None`.
- Regenerate the TypeScript client via `scripts/make_fastapi_client.py`.

**Acceptance:**
- `curl http://localhost:8000/api/cloud-reconciliation?from_date=2026-06-01&to_date=2026-06-07 | jq`
  returns a payload with all fields populated for AWS.
- Same curl with the dev config flipped to `platform = Azure` returns
  `null` (or the `{ available: false }` shape we choose).
- TypeScript client compiles.

**Rollback:** revert the four server files and regenerate the client.

---

### CP6 — `SummaryCards.tsx`: platform-aware `hasSegmented`

**Touches:** `client/src/components/SummaryCards.tsx` (one line).

```ts
const hasSegmented = metrics.total_compute_cost != null
  && cloudConfig?.platform !== 'AWS';
```

Per-cluster Cost Breakdown card now renders the existing two-row fallback
(`Cloud Costs / Databricks Costs`) for AWS and stays segmented for Azure.

**Acceptance:**
- Visual diff on `/` with `platform=AWS`: card shows two rows, no
  `$0.00` storage/network rows.
- Visual diff with `platform=Azure`: card unchanged (still four segments).
- `CoverageTrendChart` no longer renders below the cards for AWS (gated by
  the same `hasSegmented`).

**Rollback:** revert the one-line change.

---

### CP7 — `WorkspaceSharedCostCard.tsx` + hook + audit pass

**Touches:** `client/src/components/WorkspaceSharedCostCard.tsx` (new),
`client/src/hooks/useJobSpends.ts` (new hook
`useCloudReconciliation(dateRange)`).

New card, top section = category bar with the existing
compute/storage/network/other color palette, bottom section = expandable
service-level list reusing `OtherCostBreakdownModal.tsx` styling. Hidden
when `cloudConfig?.platform !== 'AWS'`.

**Audit pass (mandatory, part of this CP):** walk every consumer of
`total_storage_cost / total_network_cost / total_other_cost` in
`client/src/` and confirm no view renders a `$0.00` row for an AWS cluster.
Confirmed consumers (from `grep`):

- `SummaryCards.tsx` — handled by CP6.
- `AllPurposeSummaryCards.tsx` — needs the same `hasSegmented` cloud-aware
  fix.
- `JobBreakdownModal.tsx` — verify segment rows are hidden when value is
  null vs. zero.
- `GroupedJobTable.tsx`, `JobSpendTable.tsx` — verify column rendering.

Each finding either lands in this CP (small fixes) or gets a TODO comment
plus a v2 ticket.

**Acceptance:**
- Card renders on AWS dashboard with real data, hidden on Azure.
- No AWS view shows `$0.00` storage/network rows anywhere in the app.

**Rollback:** delete the new files, revert the hook addition, revert any
audit-pass fixes.

---

### CP8 — `AccountReconciliationCard.tsx`

**Touches:** `client/src/components/AccountReconciliationCard.tsx` (new).

Three-number tile (per-cluster, workspace-shared, workspace-total) plus
residual badge with thresholded color:

- residual `< $50` absolute OR `|residual_pct| < 3%` → green
- 3% ≤ `|residual_pct|` ≤ 10% → amber
- `|residual_pct|` > 10% → red, with tooltip pointing to
  `dbspend360_error_log` and the `RECONCILIATION_DRIFT` filter.

Hidden when `cloudConfig?.platform !== 'AWS'`.

**Acceptance:**
- Card renders with correct math on AWS.
- Three threshold cases tested by manipulating the query date range to hit
  known good (<3%), mid (5%), and bad (>10%) residuals.

**Rollback:** delete the file.

---

### CP9 — Layout integration in `JobClustersDashboard.tsx`

**Touches:** `client/src/components/JobClustersDashboard.tsx`.

Place the two new cards in their own grid row, below `SummaryCards` and
above the jobs table. Order: shared-cost card left (drill-down),
reconciliation card right (headline number). The row itself is gated by
`cloudConfig?.platform === 'AWS'` so non-AWS deployments see no empty grid
row.

**Acceptance:**
- AWS: new row appears with two cards.
- Azure / GCP: layout byte-identical to pre-CP9.

**Rollback:** revert the layout edit.

---

### CP10 — Demo readiness: backfill, docs, demo cell

**Touches:** `jobs/notebooks/aws_cloud_cost_explorer_app.ipynb` (backfill
gate), `release/AWS Credentials and Permissions Setup.md` (docs),
new `jobs/notebooks/_aws_reconciliation_demo.ipynb` (delete-after-demo
inspection cell).

**10a. Backfill gate.** On first run of CP3+CP4, detect zero rows in
`dbspend360_workspace_total_costs` and trigger a 90-day backfill instead of
the normal overlap-days window:

```python
if spark.table(self.workspace_total_table).filter(F.col("cloud_provider") == "AWS").count() == 0:
    self.logger.info("First-run backfill: querying last 90 days for workspace-total + shared bucket.")
    start_dt = datetime.now(timezone.utc).date() - timedelta(days=90)
```

Same gate, separately, for the shared breakdown rows
(`scope='workspace_shared'`).

**10b. Docs.** Update `release/AWS Credentials and Permissions Setup.md` to
note that the workspace-total CE call uses the existing
`ce:GetCostAndUsage` permission — no IAM change required. Add a section
"Dedicated vs shared AWS accounts" calling out that the residual number is
meaningful only when the AWS account is dedicated to Databricks.

**10c. Demo inspection cell.** Standalone notebook that prints the three
reconciliation numbers for the same window as the dashboard, plus the
expected residual, so the presenter can sanity-check before the demo.

**Acceptance:**
- Fresh deploy run produces ~90 days of rows in both new data surfaces.
- Docs updated.
- Demo cell prints the three numbers and matches the dashboard.

**Rollback:** revert each piece independently; backfill data can be deleted
via `DELETE FROM ... WHERE cost_incurred_date < <today - overlap_days>` if
needed.

## 7. Acceptance summary (end-to-end)

After CP10:

- `platform = AWS` dashboard shows: existing 4-up summary cards →
  collapsed two-row per-cluster Cost Breakdown → new
  WorkspaceSharedCostCard (left) + AccountReconciliationCard (right) → jobs
  table.
- `platform = Azure` dashboard is byte-identical to before this PR.
- `platform = GCP` dashboard is byte-identical to before this PR.
- `dbspend360_other_cost_breakdown` has rows with both `scope='per_cluster'`
  and `scope='workspace_shared'`. AWS rows have populated `category`; older
  rows have `category='other'`.
- `dbspend360_workspace_total_costs` has one row per day per cloud
  provider, AWS-only in this PR.
- Failure of either new CE call writes to `dbspend360_error_log` and does
  not break the DAB DAG.

## 8. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Residual on demo day is amber/red | CP10 backfill gives 90 days of history; threshold tuning in CP8 absorbs normal CE drift; if customer account is shared with non-DBX workloads we hide the card (CP9 gate) and document the assumption (CP10b). |
| Schema migration on `dbspend360_other_cost_breakdown` breaks Azure path | CP2 lands before any consumer changes; Azure notebook is re-run as part of CP2 acceptance. |
| Audit log fills with `WORKSPACE_TOTAL_WRITE_FAILED` if CE permission missing | The error is non-blocking by design (CP4 try/except). Investigate via `dbspend360_error_log` filter. |
| `CoverageTrendChart` shows a discontinuity at the CP3 cutover | Acceptable — the chart is documented as showing classification coverage, which for AWS is now structurally undefined. Pre-CP3 points stay; no new AWS points after CP3. |
| Backfill CE call exceeds rate limit | Existing `_query_with_retries` handles `LimitExceededException` with exponential backoff up to 5 attempts. Backfill is 90 days = 3 chunks of 30 days = 6 CE requests total per CE call type — well within practical limits. |
| Multi-currency rows in workspace-total | `merge_workspace_total` PKs on `(date, cloud_provider, currency)`; multiple currencies produce multiple rows per day. UI sums per currency. |

## 9. Open questions

These are genuinely undecided. None block CP1–CP4; flag answers before
CP5.

1. **API response shape when `cloud_platform != AWS`:** `null` body or
   `{ available: false }` object? Recommendation: `{ available: false }` so
   the React Query hook always gets a non-null object and the UI can render
   a "Not applicable on Azure" placeholder if we ever want one.
2. **Should the `__workspace_shared__` sentinel cluster_id be filtered out
   of every existing cluster-level query?** Audit pass in CP7 covers
   client-side; need an equivalent server-side audit before CP5 ships. Most
   likely the answer is "every `WHERE cluster_id = ?` is fine, every
   `GROUP BY cluster_id` needs an `AND cluster_id != '__workspace_shared__'`
   filter".
3. **Should the demo-cell notebook (CP10c) live in `jobs/notebooks/` or a
   new `jobs/sandbox/`?** Convention is "delete after use", but if it
   accidentally gets deployed via DAB it'll surface as a phantom task.
   Recommendation: `jobs/sandbox/_aws_reconciliation_demo.ipynb` (leading
   underscore + sandbox dir, excluded from DAB).

## 10. Resolved design issues

These are corrections to the earlier draft of this plan, captured here so
future readers don't re-litigate them.

### 10.1 — Null-out ordering vs `cloud_cost`

**Issue:** Earlier draft proposed nulling `storage/network/other` on the
aggregated DataFrame. `aggregate_costs_by_category` computes
`cloud_cost = compute + storage + network + other` *first*, then writes the
DataFrame. Nulling afterward leaves `cloud_cost` intact (good). But
`compute_quality_metrics` runs on the same DataFrame and would see
`unclassified=0` for AWS, writing a misleading `classification_coverage=100%`
to the audit log. The `CoverageTrendChart` consumes those messages and would
silently flatline at 100% for AWS days.

**Resolution:** null-out happens after aggregate, AND
`compute_quality_metrics` is short-circuited for AWS (writes
`classification_coverage=N/A` which the existing regex naturally skips).
Captured in CP3.

### 10.2 — `hasSegmented` doesn't auto-collapse from null-out alone

**Issue:** Earlier draft claimed nulling `storage/network/other` would make
`hasSegmented = metrics.total_compute_cost != null` evaluate false for AWS.
It doesn't — `compute_cost` stays populated, so `hasSegmented` stays true,
so the segmented view renders with `$0.00 — 0.0%` rows for the nulled
columns (because `?? 0` collapses NULLs).

**Resolution:** Make `hasSegmented` platform-aware in `SummaryCards.tsx`
itself (and `AllPurposeSummaryCards.tsx`). Captured in CP6, CP7 audit.

### 10.3 — Cascade audit was missing

**Issue:** The same four columns power ~5 React views and ~20 SQL SUM
sites. Nulling without an audit pass will produce zero-rows in views the
plan didn't enumerate.

**Resolution:** CP7 contains an explicit audit pass with the consumer list
from the `grep` output. Server-side audit captured in §9 open question 2.

### 10.4 — Workspace-total CE filter scope

**Issue:** Earlier draft proposed no-Filter CE call ("true workspace
total"). Fine for dedicated AWS accounts, misleading for shared accounts
(reconciliation residual includes Bedrock, RDS, etc. that are not DBX
workloads).

**Resolution:** Use the same SERVICE filter as the per-cluster call.
Residual then answers "of the DBX-related AWS services, what fraction did
DBSpend360 attribute?" — honest and meaningful regardless of account
sharing model. Captured in CP4.

### 10.5 — Reconciliation thresholds too tight

**Issue:** Earlier draft proposed 1% / 5% thresholds. AWS CE AmortizedCost
typically drifts 2–4% from the final invoice due to RI/SP amortization
timing, before any tag-propagation lag. 1% green threshold would show
amber/red on most days for no real reason.

**Resolution:** 3% green / 3–10% amber / >10% red, with an absolute floor
(residual < $50 always green). Captured in CP8.

### 10.6 — DAB DAG fragility

**Issue:** Two new CE calls inside the existing `cloud_cost_explorer` task
could break downstream `Dbspend360dbu_costs`,
`Dbspend360_all_purpose_dbu_costs`, `Dbspend360_pool_dbu_costs` if either
new call raises — even though the per-cluster data was fine.

**Resolution:** Both new writes wrapped in try/except, errors logged to
`dbspend360_error_log`, task exits SUCCESS. Captured in CP3, CP4.

### 10.7 — Backfill story for new data surfaces

**Issue:** `dbspend360_cloud_cost_explorer` has up to 365 days of history;
the two new surfaces start at zero on deploy day. Demo windows that
straddle the deploy boundary would show "no data" for the reconciliation
card on most days.

**Resolution:** One-shot 90-day backfill on first run, gated by zero-row
detection. Captured in CP10a.

## 11. v2 follow-ups (not in this plan)

- SQL Warehouse cost attribution via parallel CE call grouped by
  `WarehouseId` tag → new `dbspend360_warehouse_costs` table.
- Same shared/total/reconciliation pattern for Azure (Cost Management API
  equivalent of the no-GroupBy workspace-total call) for parity.
- Workspace-shared cost per-cluster proportional allocation, as an opt-in
  chargeback mode (toggle in `config/app.dev.config`).
- Switch primary AWS source from CE to Cost and Usage Reports (CUR) for
  hourly granularity and explicit `line_item_resource_id` tagging — IAM
  policy already reserves `cur:DescribeReportDefinitions` and S3 read.
