# Plan: AWS cost-accuracy cleanup (Job Cluster + All-Purpose tabs)

Branch: `feat/aws-cost-scope-redesign` (off `main`, working tree clean).
Scope: **AWS only.** Azure/GCP tabs, ETL, and wording are explicitly untouched.

This supersedes the older `docs/plan_aws_cost_attribution_reconciliation.md`
for anything AWS-attribution related. That doc is background only; the empirical
evidence below invalidates its workspace-shared / reconciliation direction.

> **Revision note (war-room v2).** This version closes four gaps the first
> draft missed, all of which stem from the same root cause: the first draft
> applied the `platform === 'AWS'` gate in *some* places but let three others
> fall back to the data-shape check (`compute_cost == null`). The data-shape
> check silently re-introduces the dishonest segmented view on (a) the
> All-Purpose tab and (b) the breakdown pie for runs that straddle the deploy
> date. The four corrections:
>
> 1. **All-Purpose tab is now in scope** (§4.6) — same explorer table, same
>    bug. Gated on `isAws` like the Job Cluster tab.
> 2. **The breakdown pie/legend is gated on `isAws`, not the model's data
>    shape** (§4.3, JobBreakdownModal) — a 2-slice cost_split is built
>    client-side for AWS. The earlier "the pie auto-corrects" claim was wrong.
> 3. **`EC2 / EBS` is hard-wired** in every AWS-gated FE branch (§4.4) — never
>    routed through `compute_display_name` (which yields `"EC2 Cost"`).
> 4. **The two minor cleanups are addressed**, not just noted (§4.7): the fake
>    AWS classification-coverage audit write, and the `platform=Unknown`
>    fail-open.
>
> **Revision note (war-room v3).** v2 still left the same root cause partially
> open — it gated *most* render paths but missed one drill-down and left the
> gate keyed negatively (`!isAws`), which silently routes the `Unknown`/loading
> states back onto the data-shape path. v3 closes this class of bug
> structurally rather than per-site:
>
> 1. **MAJOR-1 — the `AllPurposeUsersTable` per-cluster drill-down
>    (`UserClusterBreakdown`, `:389-411`) is now gated** (§4.6). v2 gated only
>    the parent columns and missed this `compute_cost != null` branch, which
>    still renders the fake Compute/Storage/Network split and an `EC2:` label on
>    AWS — the exact dishonesty this plan exists to kill.
> 2. **MEDIUM-2 — the gate fails *safe*, not negative** (§4.0, D14). The
>    segmentation decision is now a *positive* allowlist
>    (`platform === 'Azure' || 'GCP'`); `AWS`, `Unknown`, and the loading window
>    all render the always-correct 2-slice. `!isAws` is no longer used to drive
>    the segmented data branch.
> 3. **One shared gate, not N literals** (§4.0, D16). A single `useIsAws()` /
>    `useIsSegmentedPlatform()` hook + an exported `AWS_CLOUD_LABEL = 'EC2 / EBS'`
>    const replace the per-component flags and the five hard-wired label
>    literals, plus a **CI regression grep** that fails the build if a
>    data-shape (`compute_cost (!=|==) null`) branch or a `compute_service` /
>    `compute_display_name` label ref survives in the AWS-gated render paths.
> 4. **MEDIUM-3/4 — an ETL safety net** (§4.8, D15): a pre-merge reconciliation
>    assert that the `DEFAULT_SERVICES` shrink drops no `ClusterId`-tagged cost,
>    plus a monitor/alarm if AWS `cloud_cost` collapses to ~0 or `EC2 - Other`
>    disappears from the CE response.
> 5. **MINOR-5/6/7 — honesty boundary stated explicitly** (§6, §8): the JobBreakdownModal
>    `<Cell>` map (`:138`) is added to the edit list; the FE-only honesty boundary
>    (direct table/API/LLM consumers still see historical fabricated segments) is
>    documented; the ~25% untagged-EC2 exclusion is escalated to stakeholder comms.

---

## 1. Why

On a shared, multi-workload AWS account, only **tagged (`ClusterId`) cost is
trustworthy Databricks cluster spend**. The live 3-day CE run
(2026-06-17 → 06-20, AmortizedCost) showed:

| Service        | tagged ($) | untagged ($) | meaning |
|----------------|-----------:|-------------:|---------|
| EC2 - Compute  |   1,118.68 |       417.56 | untagged = other EC2 / maybe DB serverless/SQL/pools |
| EC2 - Other    |     159.82 |       576.97 | tagged ≈ EBS on cluster instances |
| S3             |       0.00 |     2,827.96 | ~67% of "shared"; Kinesis/DynamoDB/data-lake, **not** Databricks |
| VPC            |       0.00 |       393.95 | account-wide networking |

Derived facts that drive this plan:

- **Trustworthy Databricks cluster AWS spend = tagged only = $1,278.50.**
- Per cluster, **only `EC2 - Compute` and `EC2 - Other` carry `ClusterId`.** There
  is no standalone `Amazon Elastic Block Store` and no `AWS Data Transfer`
  service in this account (EBS folds into `EC2 - Other`). So tagged cluster cost
  = EC2 instances + their EBS, nothing else.
- Because both EC2 lines map to "compute" and there's no separate EBS service,
  **tagged `cloud_cost` == tagged `compute_cost`** → the two per-cluster cloud
  columns are redundant and collapse to one.
- The old "Workspace-Shared (Untagged)" (~$4,216, ~67% S3) was never Databricks
  infra, and the reconciliation badge was meaningless (tagged + everything-else
  ≈ account total by construction; attribution rate ~23%).

---

## 2. Ground-truth corrections (read before implementing)

These differ from the task brief's assumptions; verified by grep/read across the
clean tree:

1. **Most "removal" targets do not exist in code.** There is **no**
   `get_cloud_reconciliation`, **no** `get_workspace_total_daily`, **no**
   `compute_and_log_residual`, **no** `__workspace_shared__`, **no** no-GroupBy
   workspace-total CE call, and **no** `dbspend360_workspace_total_costs` DDL.
   `WorkspaceSharedCostCard.tsx` / `AccountReconciliationCard.tsx` are absent.
   They lived only in the discarded attempt. **Backend / endpoint / ETL "cleanup"
   is therefore a no-op — the action is "don't re-introduce."**

2. **The two ETL "bugs" are subsumed by the filter shrink, not separate work.**
   - Shrinking `DEFAULT_SERVICES` to the EC2 pair deletes the dead
     `Amazon Elastic Block Store` / `AWS Data Transfer` entries by construction.
   - `Elastic Load Balancing` is untagged ($34, account-wide, no `ClusterId`) →
     not cluster-attributable → **removed entirely.** The name-mismatch fix is
     moot.

3. **`dbspend360_other_cost_breakdown` is SHARED and used by Azure/GCP.** Do not
   drop this table. Its `scope` / `category` columns are vestigial for *all*
   platforms (the shared `write_other_cost_breakdown` never writes them and
   `get_other_cost_breakdown` never reads them; populated only by the DDL
   back-fill).

4. **Gating must key on `platform === 'AWS'`, not `compute_cost == null`.** This
   is the single most important correction, and it applies to **every** consumer
   of the explorer table, not just the Job Cluster tab. The first draft honored
   it in `GroupedJobTable`/`SummaryCards` but missed three data-shaped checks
   that this revision fixes:
   - `server/models/job_spend.py:99` — `has_segmented = compute is not None`
     drives the breakdown pie's `cost_split`. For a run straddling the deploy
     date, `SUM(compute_cost)` is partial while `SUM(cloud_cost)` is full → the
     pie under-reports cloud spend. **Gate the pie on `isAws` client-side
     (§4.3); do not trust the model's `cost_split` on AWS.**
   - `AllPurposeSummaryCards.tsx:99`, `AllPurposeClustersTable.tsx:321,509`,
     `AllPurposeUsersTable.tsx:194` — all use `compute_cost != null`. The
     All-Purpose tab reads the same explorer table and must be gated too (§4.6).
   The frontend has `useCloudPlatform().config.platform` (`"AWS"|"Azure"|"GCP"`)
   for the explicit gate, with the `platform=Unknown` fail-open handled in §4.7.

5. **Label is hard-wired, not config-derived.** `config_loader.py:215` maps AWS
   `compute_service = "EC2"`, and `get_compute_display_name()` →
   `"EC2 Cost"`. Routing the label through `compute_display_name` (as the first
   draft's §4.3 did) ships `"EC2 Cost"`, not `"EC2 / EBS"`. **Keep config as
   `"EC2"`; hard-wire the literal `"EC2 / EBS"` in every AWS-gated FE branch**
   (§4.4). This also avoids leaking `/ EBS` into LLM prompts and other
   `compute_service` consumers.

---

## 3. Decisions (settled)

| # | Decision |
|---|----------|
| D1 | Per-cluster AWS cloud column label: **`EC2 / EBS`**, hard-wired in FE (not via config). |
| D2 | `Total Cost` = DBU + tagged `EC2/EBS`, with caveat tooltip: *"excludes non-attributable AWS shared infra"*. |
| D3 | AWS Job Cluster columns: `EC2 / EBS` (from `cloud_cost`) + `DBU` + `Total`. Drop Compute/Storage/Network/Other on AWS. |
| D4 | **AWS-gated across BOTH the Job Cluster and All-Purpose tabs.** Azure/GCP segmented views stay fully intact. |
| D5 | CE SERVICE filter shrinks to the EC2 family only. Dead EBS/DataTransfer entries removed; ELB removed (not fixed). |
| D6 | One honest UI line on AWS (both tabs): *"AWS shared infrastructure (S3, NAT, networking) is not cluster-attributable and is excluded."* |
| D7 | On AWS, hide the "Other (Unclassified)" surfaces, Classification Coverage badge, CoverageTrendChart, and OtherCostBreakdownModal triggers (always empty/100% under EC2-only). Keep all for Azure/GCP. |
| D8 | AWS ETL writes `compute/storage/network/other = NULL` (mirrors Azure fallback); `cloud_cost` is the single source of truth. |
| D9 | Untagged `EC2 - Compute` (~$417): **out of scope**, documented as a known gap. |
| D10 | No "AWS Account" tab. |
| D11 | Orphaned data: one-off ops only — `DROP TABLE IF EXISTS dbspend360_workspace_total_costs`; `DELETE WHERE scope='workspace_shared'`; leave vestigial columns. |
| D12 | **The breakdown pie + legend (JobBreakdownModal) are gated on `isAws`** and rendered from a client-side 2-slice (`EC2 / EBS` + DBU) `cost_split` — not the model's data-shaped `cost_split`. |
| D13 | **The two minor cleanups are implemented**: AWS skips/relabels the `compute_quality_metrics` audit write (no fake 100% coverage row); the FE gate fails *safe* — `platform=Unknown`/loading render the 2-slice, not the segmented view (§4.0, §4.7). |
| D14 | **The segmentation gate is a positive allowlist, not `!isAws`.** Segmented compute/storage/network is shown only when `platform === 'Azure' \|\| platform === 'GCP'`. `AWS`, `Unknown`, and the config-loading window all fall to the always-correct 2-slice (`cloud_cost` + DBU). This neutralizes the straddle-period under-report on every fail-open/first-paint path (MEDIUM-2). |
| D15 | **ETL gets a safety net (MEDIUM-3/4).** Pre-merge: assert the dropped CE services carry zero `ClusterId`-tagged cost (or tagged total under the new filter == old). Ongoing: a monitor/alarm fires if AWS `cloud_cost` drops to ~0 or `EC2 - Other` disappears from the CE response (§4.8). |
| D16 | **One shared gate + one label const + a CI guard.** A single `useIsAws()` / `useIsSegmentedPlatform()` hook and an exported `AWS_CLOUD_LABEL = 'EC2 / EBS'` replace the per-component flags/literals; a CI grep asserts no data-shape or `compute_service`/`compute_display_name` branch survives in AWS-gated render paths (§4.0). This is the durable defense against the Nth-gate miss (MAJOR-1's root cause). |
| D17 | **The honesty boundary is FE-only and documented, not data-mutating.** Historical AWS rows in `dbspend360_cloud_cost_explorer` keep populated compute/storage/network; the model's `cost_split` and `coverage` KPI stay data-shaped. Direct table queries, CSV/exports, and LLM prompts still read the historical fabricated split. No backfill in this plan; the limitation is stated in §6/§8 (MINOR-6). |

---

## 4. Change spec

### 4.0 Shared gate foundation (NEW — D14, D16; MEDIUM-2 + MAJOR-1 root cause)

The first two drafts re-derived `const isAws = config?.platform === 'AWS'` in each
component and hard-wired the `'EC2 / EBS'` literal five times. That per-site
repetition is *why* a gate gets missed (MAJOR-1) and *why* the fail-open routes
to the data-shape path (MEDIUM-2). Centralize both:

**(a) One hook module** — `client/src/hooks/useCloudGate.ts` (or co-located in
`CloudPlatformContext.tsx`):

```ts
export const AWS_CLOUD_LABEL = 'EC2 / EBS';

export function useIsAws(): boolean {
  const { config } = useCloudPlatform();
  return config?.platform === 'AWS';
}

// Positive allowlist: segmented compute/storage/network is shown ONLY for
// platforms we know emit a full segmentation. AWS, Unknown, and the loading
// window (config === null) all return false → callers fall to the 2-slice.
export function useIsSegmentedPlatform(): boolean {
  const { config } = useCloudPlatform();
  return config?.platform === 'Azure' || config?.platform === 'GCP';
}
```

**(b) The segmentation rule is positive, never `!isAws`.** Every component that
chooses between the segmented breakdown and the 2-slice uses:

```ts
const isAws = useIsAws();                       // for AWS labels / column drop
const isSegmentedPlatform = useIsSegmentedPlatform();
const showSegmented = hasSegmented && isSegmentedPlatform;  // NOT `&& !isAws`
```

Rationale (MEDIUM-2): `cloud_cost + databricks_cost === total_cost` on every
platform (verified: `databricks_service.py:409`), so the 2-slice is always
correct. The segmented per-segment dollars are only trustworthy when the ETL
actually populated them — i.e. Azure/GCP. Keying on `!isAws` lets `Unknown`
(config-fetch failure) and the brief `config === null` loading window fall onto
the data-shape path, which on a straddle window computes per-segment values from
a *partial* `SUM(compute_cost)` against a *full* `SUM(cloud_cost)` → understated
Compute/Storage/Network dollars. The positive allowlist removes that path
entirely. (AWS-specific *labels* and *column dropping* still key on `isAws`;
only the segmented-vs-2-slice data branch uses the allowlist.)

**(c) CI regression grep (D16).** Add a check (test or `claude_scripts/`
script wired into CI) that fails if any AWS-gated render path still contains a
data-shape branch or a config-derived cloud label. Concretely, across the six
gated components (`GroupedJobTable`, `SummaryCards`, `JobBreakdownModal`,
`AllPurposeSummaryCards`, `AllPurposeClustersTable`, `AllPurposeUsersTable`),
assert **zero** matches for:

- `compute_cost\s*(!=|==|!==|===)\s*null` used to drive a render branch
  (data-shape gate — must be replaced by `showSegmented` / `isSegmentedPlatform`).
- `compute_service` or `compute_display_name` used as a *label* inside an
  `isAws` branch (must be `AWS_CLOUD_LABEL`).

This converts "did we catch every gate?" from human vigilance into an enforced
invariant; it is the single most important addition because it is the only thing
that would have caught MAJOR-1 mechanically.

### 4.1 ETL — `jobs/notebooks/aws_cloud_cost_explorer_app.ipynb` (cell 5 + cell 6)

**(a) Shrink the CE SERVICE filter.** In `AWSCostClient.DEFAULT_SERVICES`:

```python
DEFAULT_SERVICES = [
    "Amazon Elastic Compute Cloud - Compute",
    "EC2 - Other",  # EC2 ancillary incl. EBS on cluster instances
]
```

This is the only field that affects the CE `GetCostAndUsage` `Filter`. Removing
the other five entries drops the dead `Amazon Elastic Block Store` /
`AWS Data Transfer`, the untagged `Elastic Load Balancing`, and the account-wide
`Amazon Simple Storage Service` / `Amazon Virtual Private Cloud`.

**(b) Stop classifying; write a single attributed bucket with NULL segments.**
Replace the classify → breakdown → aggregate block in `AWSCostReporterApp.run()`
with a direct aggregation that mirrors the Azure fallback:

```python
agg_df = (
    inc_df
    .groupBy("cluster_id", "currency", "cost_incurred_date")
    .agg(F.sum("cost").alias("cloud_cost"))
    .withColumn("compute_cost", F.lit(None).cast("double"))
    .withColumn("storage_cost", F.lit(None).cast("double"))
    .withColumn("network_cost", F.lit(None).cast("double"))
    .withColumn("other_cost",   F.lit(None).cast("double"))
    .withColumn("created_at", F.current_timestamp())
    .withColumn("updated_at", F.current_timestamp())
)
```

Then:
- **Remove the AWS write to `dbspend360_other_cost_breakdown`** — no `other`
  category remains. (`utils_common`'s `write_other_cost_breakdown` stays for
  Azure/GCP.)
- **Drop the now-dead AWS classification machinery**: `AWS_SERVICE_CATEGORIES`,
  `build_aws_category_column`, and `AWSCostReporterApp._log_unclassified_services`.
- **(MINOR-4 fix, D13)** **Do not emit the fake AWS classification-coverage
  audit row.** `compute_quality_metrics` resolves to `coverage=100.0,
  unclassified=0` under an EC2-only filter, and
  `get_classification_coverage_trend` (`databricks_service.py:1790`) parses any
  `table_name='dbspend360_cloud_cost_explorer'` SUCCESS row with **no
  platform/source filter** (L1813) — so it would record a permanent fake 100%
  coverage for AWS. In the AWS branch, **either skip the
  `compute_quality_metrics` audit write entirely, or emit a non-parseable
  message** (e.g. `classification=n/a (single-bucket EC2)`) so the audit log
  carries no dishonest coverage number. Hidden from the UI by D7, but this keeps
  the audit artifact honest.
- Remaining validators are NULL-safe (`validate_no_negative_costs`,
  `validate_source_schema`, `validate_currency_consistency`).

Net behavior: `dbspend360_cloud_cost_explorer` AWS rows have
`cloud_cost = tagged EC2+EBS`, `compute/storage/network/other = NULL`. The
downstream rollup `dbspend360_total_job_spends` inherits the same shape.

> Note: the rollup notebooks that join cloud cost must preserve NULL (not
> coalesce-to-0) for the segmented columns. Verified clean in the current tree
> (`databricks_job_spends_app.ipynb` passes `cc.compute_cost` through at L239 and
> only `coalesce(...,0)`s the `total_cost` sum); re-confirm during implementation.

### 4.2 Backend — `server/services/databricks_service.py`, `server/routers/dashboard.py`, `server/models/job_spend.py`

**No removals.** The segmented fields stay `Optional[...]`; on AWS they come back
`null` and the FE gate hides them.

- `get_summary_metrics`, `get_job_cost_breakdown`, `get_top_jobs`,
  `get_grouped_job_spends`, `get_job_runs`, and the All-Purpose metric getters
  (`get_all_purpose_summary_metrics` L1852+) are unchanged. They `SUM(...)` the
  segmented columns and tolerate NULL.
- **`server/models/job_spend.py:92-116` (`CostBreakdown.__init__`) is left
  as-is** — its `has_segmented = compute is not None` branch is correct for
  Azure/GCP, and the AWS pie is now built **client-side** from the gate (§4.3,
  D12) rather than depending on this model logic. (We do **not** try to
  platform-gate the model: it has no `platform` in scope, and keeping the fix in
  the FE keeps rollback FE-only.)
- `get_other_cost_breakdown`, `get_classification_coverage_trend`, and their
  routes **stay** — Azure/GCP use them. The FE just stops calling them on AWS.
- `/api/cloud-platform` already returns `platform` — the gate source.

### 4.3 Frontend — Job Cluster tab (explicit AWS gate)

Use the shared hooks from §4.0 — do **not** re-derive `isAws` per component or
re-hard-wire the label literal:
```ts
const isAws = useIsAws();
const isSegmentedPlatform = useIsSegmentedPlatform();
// label: AWS_CLOUD_LABEL ('EC2 / EBS'); segmentation: hasSegmented && isSegmentedPlatform
```

**`client/src/components/GroupedJobTable.tsx`**
- Build the `columns` array conditionally. When `isAws`, drop the
  `total_compute_cost` / `total_storage_cost` / `total_network_cost` /
  `total_other_cost` column defs (L326-418). Keep `total_cloud_cost`,
  `total_databricks_cost`, `total_cost`.
- Relabel the `total_cloud_cost` header to **`AWS_CLOUD_LABEL`** when `isAws`
  (L427) — *not* `Total {compute_service} Cost`, and *not*
  `compute_display_name`. Non-AWS unchanged.
- `total_cost` header (L463): add the D2 caveat tooltip on AWS.
- `ExpandedJobRuns` (L68-159): when `isAws`, render a single
  `EC2 / EBS: {run.cloud_cost}` + `DBU` + `Total` line; skip the
  compute/storage/network/other spans (L116-138).
- The "Other" breakdown click target + `OtherCostBreakdownModal`: not rendered
  on AWS (D7).

**`client/src/components/SummaryCards.tsx`**
- Force the non-segmented Cost Breakdown branch via the **positive allowlist**
  (D14): `const showSegmented = hasSegmented && isSegmentedPlatform;` (replaces
  the current `hasSegmented = total_compute_cost != null` at L72). AWS, `Unknown`,
  and loading all render the cloud-vs-Databricks branch (L266-294), relabeled
  with the **`AWS_CLOUD_LABEL`** const (not `cloudConfig.compute_display_name`).
- Hide the Classification Coverage block (L225-255), the segmented bar
  (L257-264), and the `CoverageTrendChart` (L351-355) on AWS (D7).
- Hide the "Other (Unclassified)" row + modal trigger on AWS (L196-212, L357-362).
- Add the honest exclusion line (D6) under the AWS Cost Breakdown card.

**`client/src/components/JobBreakdownModal.tsx` — pie + legend gated on `isAws` (D12)**

The model's `cost_split` is data-shaped (`has_segmented = compute is not None`,
`job_spend.py:99`) and **is not trustworthy on AWS** for runs that straddle the
deploy date. So:

- Compute an AWS `cost_split` **client-side** when `isAws`, instead of using
  `breakdown.cost_split`:
  ```ts
  const awsCostSplit = [
    { name: AWS_CLOUD_LABEL, value: breakdown.cloud_cost, color: '#3b82f6' },
    { name: 'Databricks (DBU)', value: breakdown.databricks_cost, color: '#ef4444' },
  ];
  const pieData = isAws ? awsCostSplit : breakdown.cost_split;
  ```
- Feed `pieData` to **all three** consumers of `breakdown.cost_split`:
  the `<Pie data={...}>` (L129), the `<Pie>`'s inner `<Cell>` color map
  (`breakdown.cost_split.map(... <Cell/> ...)`, **L138** — MINOR-5: missed by
  v2; leaving it iterates 5 colors against the 2-entry `pieData`), and the
  legend/summary `.map(...)` (L150). All three currently read
  `breakdown.cost_split` directly.
- Gate the "Cost Analysis" grid (L232-290): when `isAws`, render the 2-tile
  cloud/DBU layout (L276-289) instead of the compute/storage/network/other grid
  (L234-273), with the cloud tile relabeled to **`AWS_CLOUD_LABEL`**
  (currently `{cloudConfig?.compute_service || 'Cloud'} Share`, L281).
- Hide the "Other" tile + `OtherCostBreakdownModal` trigger on AWS (L253-266,
  and the modal mount further down).

**`JobClustersDashboard.tsx`**: no structural change; it composes the above.

### 4.4 Labels — `AWS_CLOUD_LABEL = 'EC2 / EBS'` (single const)

`config_loader.py:215` keeps `compute_service = "EC2"` — **unchanged**. Every
AWS-gated FE branch references the single exported **`AWS_CLOUD_LABEL`** const
(§4.0, value `'EC2 / EBS'`), not `compute_display_name` (`"EC2 Cost"`) or
`compute_service` (`"EC2"`), and never a re-typed string literal:

- `GroupedJobTable` cloud-cost header + `ExpandedJobRuns` line.
- `SummaryCards` cloud BreakdownRow label.
- `JobBreakdownModal` client-side `cost_split` slice name + Cost-Analysis cloud
  tile.
- `AllPurpose*` cloud-cost columns / rows / both drill-down panels (§4.6).

Rationale for not editing config: changing the AWS mapping to `"EC2 / EBS"`
would propagate `/ EBS` into LLM prompts and any other `compute_service`
consumer. One gated const in the FE is the smaller blast radius — and a single
const (vs. the five literals the earlier drafts scattered) is what the §4.0(c)
CI grep can mechanically enforce.

### 4.5 Types / generated client

No type removals. The segmented `total_*` / `*_cost` fields stay optional. No
backend model change here, so no client regeneration is required.

### 4.6 Frontend — All-Purpose tab (NEW — MAJOR-1 fix, D4)

The All-Purpose tab reads the **same** `dbspend360_cloud_cost_explorer` table
via `dbspend360_total_all_purpose_spends`, and all three components currently
decide segmentation by data shape (`compute_cost != null`). After the ETL
change, new AWS rows have NULL segments and historical rows have populated
`compute_cost`, so without a platform gate this tab keeps showing the dishonest
Compute/Storage/Network breakdown and suffers the same straddle-the-deploy
under-representation. Apply the same shared gate (§4.0) used on the Job Cluster
tab — including in the **per-row drill-down panels**, which v2 missed:

```ts
const isAws = useIsAws();
const isSegmentedPlatform = useIsSegmentedPlatform();
```

**`client/src/components/AllPurposeSummaryCards.tsx`**
- Replace the segmentation gate with the **positive allowlist** (D14):
  `const showSegmented = hasSegmented && isSegmentedPlatform;` (currently
  `hasSegmented = metrics.total_compute_cost != null`, L99). Use `showSegmented`
  to choose the breakdown branch (L197).
- On AWS, render the non-segmented cloud-vs-DBU branch (L272-297) with the cloud
  `BreakdownRow` label set to **`AWS_CLOUD_LABEL`** (not
  `cloudConfig?.compute_display_name`, L276).
- Add the D6 honest exclusion line under the Cost Breakdown card on AWS.

**`client/src/components/AllPurposeClustersTable.tsx`**
- Drop the Compute / Storage / Network columns on AWS and keep a single
  **`EC2 / EBS`** column sourced from `total_cloud_cost` (segmented cells at
  L321-334; cloud cell at L335-336).
- In the per-day drill-down (`ClusterDayBreakdown`, L509-531), when `isAws`
  render the single `EC2 / EBS: {day.cloud_cost}` line and skip the
  compute/storage/network spans (currently gated on `day.compute_cost != null`
  at L509, with the `{cloudConfig?.compute_service || 'Cloud'}:` label at L528).
- Hide the "Other" drill-down trigger on AWS (L337+).

**`client/src/components/AllPurposeUsersTable.tsx`**
- Drop the Compute / Storage / Network columns on AWS (segmented cells at
  L193-204), keep a single **`EC2 / EBS`** column from the cloud total.
- **(MAJOR-1 fix — missed by v2)** Gate the per-user cluster drill-down
  (`UserClusterBreakdown`, **L389-411**) too. It currently branches on
  `cluster.compute_cost != null` (L389) and the else-branch renders
  `{cloudConfig?.compute_service || 'Cloud'}:` → **`EC2:`** (L408). When `isAws`,
  render the single `{AWS_CLOUD_LABEL}: {cluster.cloud_cost}` line and skip the
  Compute/Storage/Network/Other spans (L390-405) — identical treatment to the
  `ClustersTable` per-day drill-down above. Without this, expanding any user row
  on an AWS deploy still shows the fake segmented split and the `EC2:` label for
  historical clusters.

> Header/column construction in these tables mirrors `GroupedJobTable`: build the
> column set conditionally on `isAws` so the AWS view is `EC2 / EBS` + `DBU` +
> `Total`, and the Azure/GCP view is unchanged. Both drill-down panels
> (`ClusterDayBreakdown`, `UserClusterBreakdown`) must be gated, not just the
> parent column sets — the drill-downs are the exact paths v2 missed.

### 4.7 Minor hardening (D13)

- **MINOR-4 (audit honesty)** — handled in the ETL (§4.1b): AWS does not write a
  parseable `classification_coverage` audit row.
- **MINOR-5 (fail-safe gate)** — `CloudPlatformContext.tsx:47-52` sets
  `platform:'Unknown'` if `/api/cloud-platform` fails (and `config` is `null`
  during the initial `loading` window, L30-31). Under the old `!isAws` gate both
  states made `isAws` false → the *segmented* data-shape branch, which on a
  straddle window computes per-segment dollars from a partial `SUM(compute_cost)`
  — a money-presentation error, not merely a display regression. **The §4.0
  positive allowlist (D14) fixes this structurally:** `Unknown` and the loading
  window both yield `isSegmentedPlatform === false` → the always-correct 2-slice.
  No per-component `Unknown` handling is needed for correctness.
  - Still surface the failure visibly (not for correctness, for transparency):
    when `platform === 'Unknown'` and `error` is set, render a small "couldn't
    load cloud platform config" toast/banner so the degraded view isn't silent.
  - Keep the existing neutral placeholder (`compute_service:'Cloud'`,
    `compute_display_name:'Cloud Cost'`) — under the allowlist the 2-slice label
    falls back to `'Cloud Cost'`, which is honest for an unknown platform.

### 4.8 ETL safety net (NEW — D15; MEDIUM-3 + MEDIUM-4)

The §4.1a filter shrink rests on a single 3-day snapshot showing that the dropped
services (EBS / S3 / ELB / DataTransfer / VPC) carried **zero** `ClusterId`-tagged
cost. The CE `SERVICE` filter pre-filters the *response*, so if that assumption is
ever wrong — e.g. a standalone `Amazon Elastic Block Store` line for
provisioned-IOPS volumes or snapshots ever carries a `ClusterId` tag — the shrink
silently drops it and attributed cluster spend shrinks with **no** validation,
because every cross-check (coverage badge, other-cost breakdown, multi-service
split) is removed on AWS. After the change, AWS `cloud_cost` depends solely on
`ClusterId` tagging + a 2-service filter, with nothing to catch a regression.

**(a) Pre-merge reconciliation assert (one-time, gates the shrink).** Before
landing §4.1a, run the CE query **twice** over the same window — once with the
old 7-entry `DEFAULT_SERVICES`, once with the new 2-entry list — and assert that
the **tagged** (`ClusterId` non-empty) total is unchanged:

```python
# tagged_total = SUM(cost) over rows with non-empty cluster_id
assert abs(tagged_total_new - tagged_total_old) < EPS, (
    f"DEFAULT_SERVICES shrink dropped tagged cost: "
    f"old={tagged_total_old}, new={tagged_total_new}; "
    f"a dropped service carries ClusterId — re-include it before shrinking."
)
```

Equivalently, assert the dropped services (EBS/S3/ELB/DataTransfer/VPC) return
zero rows after `filter_valid_cost_rows`. Keep this as a one-off check in
`claude_scripts/` (run during implementation, not wired into the recurring job).

**(b) Ongoing monitor/alarm.** Add a lightweight post-write check in the AWS
notebook (or a separate audit job) that flags either failure mode and emits a
non-silent signal (log at ERROR + audit row, or a Databricks SQL alert):

- AWS `cloud_cost` for the window collapses to ~0 (tagging lapse), or
- `EC2 - Other` (or `Amazon Elastic Compute Cloud - Compute`) disappears from the
  CE response entirely (AWS service rename) — i.e. the 2-service filter returns
  one or zero of its expected services.

> **Comparability caveat (MEDIUM-4).** The *definition* of AWS `cloud_cost`
> changes at deploy (was "classified multi-service sum", becomes "tagged EC2+EBS
> sum"). Pre/post numbers under the same `cloud_cost` label are **not** directly
> comparable across the deploy boundary. Note the cutover date in the audit log /
> release notes so trend charts spanning the deploy aren't misread as a real
> spend drop. There is still no ground-truth check against the actual AWS bill;
> that is an accepted limitation (the bill includes non-attributable shared infra
> by construction — §1).

---

## 5. Data cleanup (one-off, live workspace — not repo code)

Run against the live UC schema (`dbspend360.04june`), gated by existence:

1. `DROP TABLE IF EXISTS dbspend360.04june.dbspend360_workspace_total_costs;`
2. `DELETE FROM dbspend360.04june.dbspend360_other_cost_breakdown
    WHERE scope = 'workspace_shared';`
   — verified safe: no code path writes `scope` (only the DDL back-fill did), so
   this matches only orphaned rows; Azure/GCP cannot legitimately produce that
   value.
3. Leave the `scope` / `category` columns and their DDL as-is (vestigial,
   unread; `get_other_cost_breakdown` selects explicit columns and
   `validate_source_schema` checks presence, not absence, of columns).

Keep these as a short, idempotent SQL snippet in `claude_scripts/` (not wired
into the DABs job).

---

## 6. What stays platform-conditional

- Azure/GCP keep segmented compute/storage/network/other end-to-end across
  **both** tabs (backend + all six frontend components keep their segmented
  branches for non-AWS).
- `dbspend360_other_cost_breakdown`, `/api/other-cost-breakdown`,
  `/api/classification-coverage-trend`, `CoverageTrendChart`,
  `OtherCostBreakdownModal`: retained, used by Azure/GCP, suppressed on AWS.
- `get_cluster_details` AWS/Azure/GCP attribute blocks: unchanged.
- `CostBreakdown.__init__` model logic: unchanged (Azure/GCP rely on it; AWS pie
  is FE-built).

### 6.1 Honesty boundary (explicit — D17, MINOR-6)

This plan enforces honesty **in the view, not in the data.** Be explicit about
what that does and does not cover, so no one mistakes the FE gate for a
data-correctness guarantee:

- **What stays "lying" by design:** historical AWS rows in
  `dbspend360_cloud_cost_explorer` keep their populated
  `compute/storage/network/other` columns; `server/models/job_spend.py:99` keeps
  the data-shaped `has_segmented`; `get_summary_metrics` still computes a
  `coverage`/`coverage_warning` KPI from segments on AWS
  (`databricks_service.py:314-316`). The FE gate (§4.0/§4.3/§4.6) hides all of
  this — but **direct table queries, CSV/exports outside these components, and
  any LLM prompt that reads the segmented columns still see the fabricated
  split.**
- **Why no backfill (this plan):** NULL-backfilling historical AWS segments
  would make the data self-honest but is a destructive, irreversible migration
  over live history; deferred as an optional follow-up, not done here.
- **The single enforcement point:** honesty for end users rests entirely on the
  six gated components + the §4.0 CI grep. Any *new* consumer of the explorer
  table (new component, export, agent tool) must re-apply the gate or it will
  re-surface the fabricated split. This is the standing risk of the FE-only
  approach and is accepted explicitly.

---

## 7. Rollout order (safe, reversible)

1. **Frontend gate first (display-only), shipped whole + CI grep green.** Build
   the §4.0 shared hook + `AWS_CLOUD_LABEL` const first, then ship the gating in
   `GroupedJobTable` / `SummaryCards` / `JobBreakdownModal` **and** the three
   `AllPurpose*` components (parent columns **and** both drill-down panels —
   MAJOR-1) + the honest line, **all in one FE step.** Land the §4.0(c) CI
   regression grep in the same step and confirm it goes **green** — it both
   fixes the proven miss and converts "did we catch every gate?" into an enforced
   invariant before any ETL work.

   > Do **not** ship the FE gate for one tab while the other tab, the breakdown
   > pie, or either drill-down still trusts `compute_cost != null` — that's
   > exactly the gap this revision closes. Fixes §4.3 (pie, incl. the L138 Cell
   > map) and §4.6 (All-Purpose, incl. `UserClusterBreakdown` L389-411 and
   > `ClusterDayBreakdown` L509-531) must land together with the Job Cluster gate.

   This correctly renders existing AWS rows (which have `compute_cost`
   populated) as a single `EC2 / EBS` view immediately, with no ETL dependency.
   Verify locally (`./watch.sh`) on the AWS config; flip `[cloud] platform` to
   Azure to confirm both tabs still render segmented; force a
   `/api/cloud-platform` failure **and** observe the loading window to confirm
   the fail-safe 2-slice (not the segmented view) under `Unknown`/`null` (§4.0,
   §4.7).
2. **ETL safety net → shrink + NULL segments + skip coverage audit (§4.1, §4.8).**
   First run the §4.8(a) pre-merge reconciliation assert (old vs new
   `DEFAULT_SERVICES` tagged totals must match) and only proceed if it passes.
   Then deploy the notebook to
   `/Workspace/Users/aditya.mandiwal@databricks.com/deployed from cursor/jobs/notebooks/aws_cloud_cost_explorer_app`,
   run for the overlap window, and confirm new rows have
   `cloud_cost = tagged EC2+EBS`, segments NULL, **no** new
   `dbspend360_other_cost_breakdown` AWS rows, and **no** new fake
   classification-coverage audit row. Wire the §4.8(b) monitor/alarm and record
   the cutover date for trend comparability (MEDIUM-4).
3. **One-off data cleanup** (§5).
4. **Deploy the app** (`./deploy.sh`) and run the post-deploy log/endpoint checks
   (CLAUDE.md monitoring workflow): `/api/summary`, `/api/grouped-job-spends`,
   `/api/job/{id}/breakdown`, and the All-Purpose endpoints for an AWS cluster —
   verify single `EC2 / EBS` column, caveat tooltip, no coverage/Other UI,
   honest line on both tabs, totals = DBU + tagged EC2/EBS, and the pie shows
   exactly two slices.

Rollback: the FE gate is independently revertable; the ETL change is
forward-compatible (NULL segments) and the rollup keeps `cloud_cost` correct, so
reverting the FE alone restores the old segmented view for any non-NULL rows.

---

## 8. Out of scope (documented gaps)

- Untagged `EC2 - Compute` (~$417): may be Databricks serverless/SQL/pools that
  don't carry `ClusterId`. Not attributed here.
  - **Stakeholder comms (MINOR-7):** this is **~25% of the $1,278.50 "trustworthy"
    total** — material, not a rounding footnote. The "honest" Databricks AWS total
    therefore *understates* real cluster-adjacent spend by roughly a quarter.
    Surface this explicitly to stakeholders (release note / dashboard caveat),
    not just D9, so the headline number isn't read as the full AWS cluster spend.
- AWS account-total / "AWS Account" tab: deliberately not built.
- Services billed outside the EC2 filter (Kinesis, MSK, DynamoDB, RDS, Redshift,
  SageMaker, etc.): never ingested; all untagged/non-Databricks.
- **Pools tab**: unaffected — `pool_spends_app.ipynb` writes
  `cloud_cost = F.lit(None)` always and never surfaces AWS segmentation. No
  gate needed.

---

## 9. File-change checklist

- [x] `client/src/hooks/useCloudGate.ts` — shared `useIsAws()` /
      `useIsSegmentedPlatform()` hooks + exported `AWS_CLOUD_LABEL = 'EC2 / EBS'`.
      **(NEW, §4.0, D16)**
- [x] `jobs/notebooks/aws_cloud_cost_explorer_app.ipynb` — **(CP11 done)** shrunk
      `DEFAULT_SERVICES` to the EC2 pair; replaced classify/aggregate block with
      direct `cloud_cost` agg + NULL segments; removed `AWS_SERVICE_CATEGORIES`,
      `build_aws_category_column`, `_log_unclassified_services`, the AWS breakdown
      write; AWS `compute_quality_metrics` audit write replaced with a
      non-parseable `classification=n/a (single-bucket EC2/EBS)` message.
      **(CP12 done)** added `_monitor_post_write` (cloud_cost~0 / EC2 service
      missing → `logger.error` + `error_log` row) and stamped `CUTOVER_DATE` +
      `monitor_alerts=N` into the SUCCESS audit message (§4.8(b), MEDIUM-4).
- [x] `client/src/components/GroupedJobTable.tsx` — AWS-gated columns,
      `AWS_CLOUD_LABEL`, total caveat tooltip, `ExpandedJobRuns` single-bucket,
      hide Other.
- [x] `client/src/components/SummaryCards.tsx` — `showSegmented = hasSegmented &&
      isSegmentedPlatform` (positive allowlist); hide coverage/Other/trend on
      AWS; `AWS_CLOUD_LABEL`; honest line.
- [x] `client/src/components/JobBreakdownModal.tsx` — **client-side AWS
      `cost_split` for pie + `<Cell>` map (L138) + legend (L150)**; AWS-gated cost
      grid + `AWS_CLOUD_LABEL` tile; hide Other.
- [x] `client/src/components/AllPurposeSummaryCards.tsx` — `showSegmented =
      hasSegmented && isSegmentedPlatform`; `AWS_CLOUD_LABEL`; honest line. **(NEW)**
- [x] `client/src/components/AllPurposeClustersTable.tsx` — AWS-gated columns +
      `ClusterDayBreakdown` drill-down (L509-531); `AWS_CLOUD_LABEL`; hide Other.
      **(NEW)**
- [x] `client/src/components/AllPurposeUsersTable.tsx` — AWS-gated columns **+
      `UserClusterBreakdown` drill-down (L389-411) — MAJOR-1**; `AWS_CLOUD_LABEL`.
      **(NEW)**
- [x] `client/src/contexts/CloudPlatformContext.tsx` — optional "config load
      failed" banner on `platform=Unknown` (correctness now handled by the §4.0
      allowlist, not here). **(NEW, MINOR-5)**
- [x] CI regression grep (`claude_scripts/check_aws_gate.mjs` + npm
      `lint:aws-gate` + `.github/workflows/aws-gate.yml`) — fails build on
      surviving `compute_cost (!=|==) null` data-shape branch or
      `compute_service`/`compute_display_name` label in AWS-gated paths.
      **(NEW, §4.0(c), D16)**
- [x] `claude_scripts/aws_cost_recon_assert.py` — §4.8(a) pre-merge old-vs-new
      `DEFAULT_SERVICES` tagged-total reconciliation. **(NEW, MEDIUM-3)**
- [x] `claude_scripts/aws_cost_cleanup.sql` — the one-off ops (DROP orphaned
      `dbspend360_workspace_total_costs`; DELETE `scope='workspace_shared'` rows;
      vestigial columns left intact). **(CP13 done)**
- [ ] No backend/router/model/type/DDL deletions required (model
      `CostBreakdown.__init__` left intact; AWS pie is FE-built; honesty boundary
      is FE-only — §6.1, D17).

---

## 10. Implementation checkpoints

Discrete, one-at-a-time units. Each is **independently implementable, locally
verifiable, and committable**. Dependencies are noted per checkpoint; unless a
dependency is listed, a checkpoint can be done in any order within its phase.

**Hard deploy constraint (from §7):** the entire FE phase (CP1–CP9) must reach
production *together*. Implement and locally verify each FE checkpoint
incrementally, commit them separately, but do **not** run §7.4 deploy until all
of CP1–CP9 are done and the CI grep (CP9) is green. Local verification = run
`./watch.sh` and flip `[cloud] platform` between `AWS` / `Azure` / `Unknown`.

### Phase A — Frontend gate (display-only; deploy as one unit at end of phase)

- [x] **CP1 — Shared gate foundation.** §4.0(a)(b). Create
      `client/src/hooks/useCloudGate.ts` with `useIsAws()`,
      `useIsSegmentedPlatform()` (positive allowlist), and exported
      `AWS_CLOUD_LABEL = 'EC2 / EBS'`. No UI change yet.
      *Verify:* compiles; hooks return correct booleans per platform.
      *Deps:* none. **Blocks CP2–CP9.**

- [x] **CP2 — Job Cluster: `GroupedJobTable`.** §4.3. AWS-gated columns (drop
      compute/storage/network/other), `AWS_CLOUD_LABEL` header, D2 caveat
      tooltip, `ExpandedJobRuns` single-bucket line, hide Other.
      *Verify:* AWS shows `EC2 / EBS` + DBU + Total; Azure unchanged. *Deps:* CP1.

- [x] **CP3 — Job Cluster: `SummaryCards`.** §4.3.
      `showSegmented = hasSegmented && isSegmentedPlatform`; hide
      coverage/Other/trend on AWS; `AWS_CLOUD_LABEL`; D6 honest line.
      *Verify:* AWS cloud-vs-DBU breakdown, no coverage UI; Azure unchanged.
      *Deps:* CP1.

- [x] **CP4 — Job Cluster: `JobBreakdownModal`.** §4.3, D12. Client-side AWS
      `cost_split` feeding pie (L129), `<Cell>` map (L138), legend (L150);
      AWS-gated 2-tile cost grid with `AWS_CLOUD_LABEL`; hide Other tile/modal.
      *Verify:* AWS pie shows exactly 2 slices (incl. a straddle-date run);
      Azure unchanged. *Deps:* CP1.

- [x] **CP5 — All-Purpose: `AllPurposeSummaryCards`.** §4.6.
      `showSegmented = hasSegmented && isSegmentedPlatform`; `AWS_CLOUD_LABEL`;
      D6 honest line. *Verify:* AWS breakdown honest; Azure unchanged. *Deps:* CP1.

- [x] **CP6 — All-Purpose: `AllPurposeClustersTable`.** §4.6. AWS-gated columns
      (single `EC2 / EBS`) **+ `ClusterDayBreakdown` drill-down (L509-531)**;
      hide Other trigger. *Verify:* expand a cluster row on AWS → single
      `EC2 / EBS` line, no segmented spans; Azure unchanged. *Deps:* CP1.

- [x] **CP7 — All-Purpose: `AllPurposeUsersTable` (MAJOR-1).** §4.6. AWS-gated
      columns **+ `UserClusterBreakdown` drill-down (L389-411)** — single
      `EC2 / EBS` line, no `EC2:` label, no segmented spans. *Verify:* expand a
      user row on AWS → honest single-bucket; Azure unchanged. *Deps:* CP1.

- [x] **CP8 — `CloudPlatformContext` fail banner.** §4.7, MINOR-5. Surface a
      small "couldn't load cloud platform config" banner when
      `platform === 'Unknown'` and `error` is set. (Correctness already handled
      by CP1's allowlist; this is transparency only.) *Verify:* force a
      `/api/cloud-platform` failure → banner shows, 2-slice still renders.
      *Deps:* CP1.

- [x] **CP9 — CI regression grep.** §4.0(c), D16.
      `claude_scripts/check_aws_gate.mjs` (dependency-free node, comment/string
      aware) wired into CI via `client` npm `lint`/`lint:aws-gate` and
      `.github/workflows/aws-gate.yml`: fails on any surviving
      `compute_cost (!=|==) null` data-shape branch or `compute_service` /
      `compute_display_name` label in the six gated components. *Verified:* grep
      is **green** against CP2–CP7; the bundled `--self-test` (9 cases) plus a
      live `&& !isAws` injection confirmed it fails **red**, and revert restores
      green. *Deps:* CP2–CP7 (so it can pass). **Deploy gate: CP1–CP9 must all be
      done before §7.4.**

### Phase B — ETL

- [x] **CP10 — Pre-merge reconciliation assert (gates the shrink).** §4.8(a),
      MEDIUM-3. `claude_scripts/aws_cost_recon_assert.py`: runs the same CE query
      (dual GroupBy TAG+SERVICE, DAILY, exclusive end — mirrors the ETL client)
      over one window with old 7-entry vs new 2-entry `DEFAULT_SERVICES`; asserts
      the tagged (`ClusterId` non-empty) total is unchanged within `--eps` and
      itemizes tagged cost on each dropped service. Reuses the
      `dbspend-read-ce` service credential inside Databricks, falls back to
      default boto3 creds locally. *Verified:* `ruff` clean; pure
      `reconcile`/`tagged_total` self-tests pass (match-case green, injected
      dropped-service tagged cost goes red); `--help` smoke OK. **Live run PASSED**
      (2026-06-17 → 06-20, AmortizedCost, on Databricks compute with
      `dbspend-read-ce`): tagged old == tagged new == **$2016.2296**, diff
      $0.0000, and all five dropped services (EBS / S3 / ELB / DataTransfer / VPC)
      returned **$0.0000** tagged cost — the shrink drops no cluster-attributable
      cost. *Deps:* none. **CP11 unblocked.**

- [x] **CP11 — ETL change.** §4.1. In `aws_cloud_cost_explorer_app.ipynb`: shrunk
      `DEFAULT_SERVICES` to the EC2 pair; replaced classify/aggregate with direct
      `cloud_cost` agg + NULL segments; removed `AWS_SERVICE_CATEGORIES`,
      `build_aws_category_column`, `_log_unclassified_services`, the AWS
      `other_cost_breakdown` write; the AWS `compute_quality_metrics` audit write
      is replaced with a non-parseable `classification=n/a (single-bucket EC2/EBS)`
      message (no `classification_coverage=` token → no fake coverage row).
      *Verified locally:* all cells parse, `ruff` clean (only pre-existing
      `%run`-injected F821 globals), no leftover refs to removed symbols, and both
      rollups (`databricks_job_spends_app`, `all_purpose_spends_app`) pass
      `cc.compute_cost` through / preserve NULL segments. *Pending live run* for
      overlap window → confirm new rows have `cloud_cost = tagged EC2+EBS`,
      segments NULL, no new other-cost-breakdown AWS rows, no fake coverage audit
      row. *Deps:* CP10.

- [x] **CP12 — ETL monitor/alarm.** §4.8(b), MEDIUM-4. Added
      `AWSCostReporterApp._monitor_post_write` (called on every `run()` path,
      incl. the no-data path) which fires a non-silent alarm — `logger.error`
      + an `error_log` row via `write_error_log_entries(..., 'COST_MONITOR_ALARM')`
      — on either failure mode: (1) window `cloud_cost < CLOUD_COST_FLOOR`
      (=0.01) ⇒ tagging lapse/empty CE response; (2) one or both of
      `DEFAULT_SERVICES` (`EC2 - Other` / `Amazon Elastic Compute Cloud -
      Compute`) absent from the CE response ⇒ AWS service rename / filter
      drift. The cutover date (`CUTOVER_DATE='2026-06-22'`) + `monitor_alerts=N`
      are stamped into the SUCCESS audit `quality_msg` for MEDIUM-4 trend
      comparability. Advisory only — never fails the run. *Verified:* `ruff`
      clean (only pre-existing `%run`-injected F821 globals; no new undefined
      names). *Pending live run* to exercise each failure mode. *Deps:* CP11.

### Phase C — Data cleanup & deploy

- [x] **CP13 — One-off data cleanup.** §5. `claude_scripts/aws_cost_cleanup.sql`:
      `DROP TABLE IF EXISTS ... dbspend360_workspace_total_costs`;
      `DELETE ... WHERE scope = 'workspace_shared'`; leave vestigial columns.
      Both statements idempotent + existence-gated; targets the live schema
      `dbspend360.04june`; documented in `claude_scripts/README.md` as a hand-run,
      one-off (not wired into the DABs job). *Pending live run* against the SQL
      warehouse. *Verify:* idempotent; affects only orphaned rows. *Deps:* none
      (can run any time; logically after CP11).

- [x] **CP14 — Deploy + post-deploy verification.** §7.4. Ran `./deploy.sh`
      (profile `e2-demo-field-eng`, app `dbspend360-aditya`) → deployment
      `01f16db1d544189f9b840f254fd022e3` state **SUCCEEDED**, "App started
      successfully". Pre-flight: CI grep green (6 components clean, 9-case
      self-test green) + `npm run build` clean. Post-deploy logs confirmed
      `Application startup complete` / `Uvicorn running on http://0.0.0.0:8000`
      with no exceptions. AWS endpoints verified against
      `https://dbspend360-aditya-1444828305810485.aws.databricksapps.com`:
      `/api/cloud-platform` → `platform=AWS`; `/api/summary`,
      `/api/grouped-job-spends`, `/api/job/{id}/runs`, `/api/job/{id}/breakdown`,
      `/api/all-purpose/summary` all 200 with the AWS shape
      (`cloud_cost == compute_cost`, `storage/network/other = NULL`). As designed
      (D12/D17/§6.1) the model's `/breakdown` `cost_split` is still data-shaped
      (4-slice) server-side; the 2-slice AWS pie is built client-side by the
      deployed FE gate. *Deps:* CP1–CP13. **DONE.**
