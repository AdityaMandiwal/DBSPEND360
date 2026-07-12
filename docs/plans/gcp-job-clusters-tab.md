# Plan: GCP support for the Job Clusters tab (only)

> Status: proposed · Branch: `feature/gcp-support` · Scope: Job Clusters tab exclusively

## Summary

The Job Clusters tab is **already GCP-ready on the frontend and backend**. The
only real gap is the ETL layer: `jobs/notebooks/gcp_cloud_cost_explorer_app.ipynb`
is a stub that raises `NotImplementedError`, while the DBU half of the pipeline is
already cloud-agnostic. This plan implements the missing GCP cloud-cost explorer
and wires the config/DAB so the Job Clusters tab works on a GCP deployment.

## Why this is mostly an ETL task

The Job Clusters tab reads one precomputed table, `dbspend360_total_job_spends`,
built by a 3-stage chain:

```
cloud_cost_explorer  →  Dbspend360dbu_costs  →  databricks_job_spends
   (cloud VM $)            (DBU $)                 (join → total)
```

- **Stage B (DBU)** — `dbspend360_dbu_cost_app.ipynb` reads `system.billing.usage`
  + `system.billing.list_prices`, filters `cluster_source='JOB'`. No cloud
  branching. **Works on GCP as-is.**
- **Stage C (rollup)** — `databricks_job_spends_app.ipynb` inner-joins DBU ⨝ cloud
  on `(cluster_id, usage_date)`. Cloud-agnostic. **Works as-is.**
- **Stage A (cloud VM cost)** — provider-specific. AWS uses Cost Explorer API,
  Azure uses Cost Management API, **GCP is a stub.** ← *this is the work.*

The frontend already treats GCP as a "segmented platform"
(`useIsSegmentedPlatform()` in `client/src/hooks/useCloudGate.ts`), and the backend
`server/config/config_loader.py` already maps GCP → `GCE` / "Google Cloud". So no
frontend/backend code changes are strictly required beyond config.

## The one architectural difference to decide first

AWS/Azure both have a **query-time cost API** grouped by a resource tag. GCP has
**no equivalent granular Cost Explorer API** — the canonical source for
per-resource, per-label daily cost is the **BigQuery Billing Export** (detailed
usage export table `gcp_billing_export_resource_v1_XXXXXX`). That means the GCP
explorer reads a BigQuery table rather than calling a REST cost API. This changes
the client internals (BigQuery query + auth) but **not** the output contract — it
still produces the same `(cluster_id, currency, cost_incurred_date, category, cost)`
shape and reuses all the shared `utils_common` machinery.

## Locked-in decisions (defaults)

These are all isolated to the new explorer notebook + config/DAB wiring, so any can
be adjusted later without touching the DBU or rollup stages, or the frontend.

| Decision | Choice | Rationale |
|---|---|---|
| Cost data source | BigQuery detailed billing export (`gcp_billing_export_resource_v1_*`) | Only source with per-resource labels needed for cluster attribution |
| Auth | Service-account JSON key in a Databricks secret scope | A `dbspend360-bq-reader` service account already exists and works; mirrors how the Azure notebook reads `tenant_id`/`client_id`/`client_secret` from a scope. **The raw key lives only in the secret scope — never in the repo.** |
| Cluster label key | `clusterid` (lowercase) | Matches the Azure convention; **verify against the export in Phase 4** |
| Credits | Net cost (`cost + credits`) | Matches the real invoice |

## Scope guardrails (what will NOT be touched)

- No pool path (`run_pool` / `dbspend360_pool_cloud_cost_explorer`) — that's the
  Instance Pools tab.
- No all-purpose or pipeline GCP wiring.
- No new DDL tables — `dbspend360_cloud_cost_explorer` and downstream tables already
  exist and are provider-neutral.
- No frontend component changes (GCP already renders via the segmented-platform gate).

## Implementation phases

### Phase 1 — Implement `gcp_cloud_cost_explorer_app.ipynb` (the core work)

Mirror the structure of `azure_cloud_cost_explorer_app.ipynb` (Azure is the closest
reference — both are segmented, unlike AWS's single bucket):

1. **`GCPCostClient`** — queries the BigQuery billing export:
   - Filters to Databricks GCE resources by label (the cluster label key — see
     open questions).
   - Groups by `label(cluster_id)`, `service.description` (for classification),
     `usage_start_time::date`, `currency`.
   - Aggregates `SUM(cost)` and, per decision, `+ SUM(credits.amount)` for net cost.
   - Returns a Spark DataFrame with `cluster_id, service_name, cost, currency,
     cost_incurred_date`.
   - Handles incremental windows via `get_date_window()` (already in
     `utils_common`).
2. **`GCP_SERVICE_CATEGORIES`** mapping (analog of `AZURE_METER_CLASSIFICATION`):
   Compute Engine → `compute`; Persistent Disk / Cloud Storage → `storage`;
   networking SKUs → `network`; everything else → `other`. Plus a
   `classify_gcp_service()` + `build_gcp_category_column()` pair.
3. **`GCPCostReporterApp.run()`** — reuse the existing shared utils verbatim:
   `ensure_cost_columns`, `filter_valid_cost_rows`, `build_gcp_category_column` →
   `aggregate_costs_by_category`, `write_other_cost_breakdown(..., "GCP", ...)`,
   `validate_*`, `merge_cloud_cost_explorer`, `log_audit_run`,
   `validate_post_merge`. Tag audit/error rows `source_system='GCP'` / `'GCP_COST'`.
4. **Omit `run_pool()`** (out of scope). Notebook's final cell calls only
   `app.run()`.

### Phase 2 — Auth wiring (Databricks-on-GCP → BigQuery)

Use a **service-account JSON key stored in a Databricks secret scope** (the
`dbspend360-bq-reader@gcp-dev-field-eng.iam.gserviceaccount.com` account). The
notebook reads the key material from the scope via `dbutils.secrets.get(...)` and
builds `google.oauth2.service_account.Credentials` from it — mirroring how the Azure
notebook reads `tenant_id`/`client_id`/`client_secret` from its scope.

- Store the JSON key in a secret scope (e.g. `scope=dbspend360-gcp`), either as one
  `service_account_json` secret or as individual fields.
- Add notebook widgets: `billing_project`, `billing_export_dataset`,
  `billing_export_table`, `scope` — mirroring the Azure `subscription_id`/`scope`
  pattern.
- **The raw key is never written to the repo, config files, or the plan doc.** Any
  key pasted into chat/logs must be rotated.
- GCP libs to install in the notebook (first cell, like Azure's `%pip install`):
  `google-cloud-bigquery` and `google-auth`.

### Phase 3 — DAB + config wiring

- `jobs/resource_templates/DBSPEND360.yaml`: set `cloud_provider` default to `gcp`
  for the GCP deployment (resolves `${cloud_provider}_cloud_cost_explorer_app`), and
  add the new GCP widgets as job parameters (with inert empty defaults, same pattern
  as the Azure-only `subscription_id`/`scope`).
- `config/app.<env>.config`: set `[cloud] platform = GCP` and point `table_name` /
  `schema_name` at the GCP target schema.
- Deploy the notebook to the workspace path per the deployment-paths rule
  (`.../deployed from cursor/jobs/notebooks/gcp_cloud_cost_explorer_app`).

### Phase 4 — Run + verify

- Run `create_all_tables` (idempotent) in the GCP schema, then the job chain:
  `cloud_cost_explorer → Dbspend360dbu_costs → databricks_job_spends`.
- Verify `dbspend360_total_job_spends` populates with non-null `cloud_cost` for GCP
  clusters.
- Load the app with `platform=GCP` and confirm the Job Clusters tab renders the
  4-slice segmented breakdown, the coverage trend, and run drill-downs (GCP
  `gcp_attributes` already handled in `JobBreakdownModal`).

## Key risk to flag

Stage C uses an **inner join** on `(cluster_id, usage_date)`. If GCP VM labeling is
unreliable (labels missing/misspelled), job rows with DBU but no cloud match will
**silently vanish** from the tab. Phase 4 must validate label coverage; if it's
poor, we'd discuss switching that join to a left join (a separate, cross-cloud
change — out of this scope, but noted).

## Files touched

| File | Change |
|---|---|
| `jobs/notebooks/gcp_cloud_cost_explorer_app.ipynb` | Replace stub with real `GCPCostClient` + `GCPCostReporterApp` |
| `jobs/resource_templates/DBSPEND360.yaml` | `cloud_provider=gcp` default + GCP job parameters |
| `config/app.<env>.config` | `[cloud] platform = GCP`, GCP schema/table names |

Reused unchanged: `jobs/notebooks/utils_common.ipynb`,
`jobs/notebooks/dbspend360_dbu_cost_app.ipynb`,
`jobs/notebooks/databricks_job_spends_app.ipynb`, all `jobs/ddls/*`, the FastAPI
backend, and the React frontend.

## Open items to confirm before/while building

- BigQuery billing export exists and is the **detailed/per-resource** variant
  (has a `labels` array).
- The `dbspend360-bq-reader` service account has `bigquery.dataViewer` +
  `bigquery.jobUser` on the billing export dataset/project.
- The SA JSON key is loaded into the target Databricks secret scope (and the
  chat-exposed key has been rotated).
- The exact cluster label key on GCE VMs (assumed `clusterid`).
