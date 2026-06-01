# Plan — Shared Clusters & Instance Pools Tabs

Branch: `feat/shared-clusters-and-pools-tabs`

This plan extends DBSPEND360 beyond job-cluster spend by adding two new top-level tabs to the dashboard. It is split across the files in this directory; read them in numbered order.

| File | Contents |
|---|---|
| [`01-verification-spike.md`](01-verification-spike.md) | Slice 0 — read-only workspace queries to de-risk Slice 2/3 |
| [`02-architectural-decisions.md`](02-architectural-decisions.md) | §4.5 locked-in design choices |
| [`03-slice-1-ui-tabification.md`](03-slice-1-ui-tabification.md) | Slice 1 — pure-frontend refactor to introduce tabs |
| [`04-slice-2-shared-clusters.md`](04-slice-2-shared-clusters.md) | Slice 2 — Shared Clusters tab (data + API + UI) |
| [`05-slice-3-instance-pools.md`](05-slice-3-instance-pools.md) | Slice 3 — Instance Pools tab (ETL extension + API + UI) |
| [`06-cross-cutting.md`](06-cross-cutting.md) | Permissions, config flags, testing, formatting |

## 1. Goal

Extend DBSPEND360 beyond job-cluster spend by adding two new top-level tabs to the dashboard:

1. **Shared Clusters** — visibility into All-Purpose / interactive clusters (`cluster_source IN ('UI','API')`), their owners, configuration, and total cost (DBU + cloud VM).
2. **Instance Pools** — visibility into Databricks instance pools, including the headline metric **idle VM cost** (pool VMs incurring cloud spend with no cluster attached).

Today the data pipeline filters everything except `cluster_source = 'JOB'` rows with non-null `job_run_id`, so neither dimension is represented in `dbspend360_total_job_spends`. This plan covers the data, backend, and frontend work end-to-end.

## 2. Non-goals

- GCP support for either tab (the GCP cost-explorer notebook is still a stub).
- Per-user chargeback on shared clusters from `system.access.audit` (deferred — large, separate effort).
- Real-time pool utilization (we use daily granularity, same as the rest of the app).
- Modifying the existing Jobs tab behaviour or schema semantics.

## 3. Sequencing & branching strategy

Single feature branch `feat/shared-clusters-and-pools-tabs` off `main`. Internally we ship in three reviewable PR-sized chunks (squash-merge each):

| Order | Slice | Why first |
|---|---|---|
| 0 | Verification spike (read-only queries against workspace) | Confirms `usage_metadata.instance_pool_id` is populated and pool VMs carry `DatabricksInstancePoolId` cloud tags. De-risks Slice 2. |
| 1 | UI tabification refactor (no behaviour change) | Lowest risk, unblocks Slices 2 and 3 to be developed in parallel. |
| 2 | Shared Clusters tab (data + API + UI) | High value, low risk — cloud-cost join already works for `cluster_source IN ('UI','API')`. |
| 3 | Instance Pools tab (ETL extension + API + UI) | Highest risk because it requires extending the AWS / Azure cloud-cost ETL to capture the `DatabricksInstancePoolId` tag. |

## 9. Out-of-scope follow-ups (capture for backlog)

- Per-user attribution on shared mode clusters via `system.access.audit.commandSubmit`.
- Continuous pool utilization (hourly granularity using `system.compute.warehouse_events` if available).
- GCP support for both tabs (blocked on the existing `gcp_cloud_cost_explorer_app` implementation).
- SQL warehouse spend tab (logical next addition — `usage_metadata.warehouse_id`).

## 10. Definition of done

- All three slices merged into `feat/shared-clusters-and-pools-tabs`.
- README updated with new tabs, new grants, screenshots in `release/readme_images/`.
- Deployed to Databricks Apps and `dba_logz.py` shows clean `Uvicorn running` with no exceptions.
- Reconciliation queries documented in [`01-verification-spike.md`](01-verification-spike.md) re-run against production data, results pasted into a final "Verification results" section appended at the bottom of that file before PR review.
