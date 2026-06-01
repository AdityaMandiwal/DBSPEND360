# Cross-cutting work

[← back to plan index](README.md)

## Permissions / docs

- Update README §"Required Grants for the App Service Principal":
  - Add `SELECT ON system.billing.usage` (required for both new tabs).
  - **Elevate `SELECT ON system.compute.clusters` from "Optional" to "Required" for the new tabs.** Move it out of the Optional subsection. Document the degraded-mode behaviour for deployments that cannot get this grant: Shared Clusters tab shows cluster IDs only with no owner / security-mode / auto-termination; Instance Pools tab shows `pool_total_cost` but no idle vs active split.
  - Add note about `CAN VIEW` on each instance pool for the SDK call (or `CAN_MANAGE` at the account level).
- Update `docs/databricks_apis/databricks_sdk.md` with the `instance_pools.list/get` usage pattern.

## Config

- No new database / catalog config keys. Both new tables resolve under the same `catalog.schema` as `dbspend360_total_job_spends`.
- Add two feature flags in `server/config/config_loader.py` (matching the `enable_cost_analysis` / `enable_cluster_analysis` pattern):
  - `enable_shared_clusters_tab` (default `True`)
  - `enable_instance_pools_tab` (default `True`)
- Surface both flags through `/api/cloud-platform` (or a new `/api/features` endpoint) so the frontend can render the tab list conditionally. This lets Slice 1 ship safely with both new tabs hidden until the data backfill completes.

## Testing

- New tests under `claude_scripts/` to:
  - Verify endpoint shapes for shared-cluster and pool endpoints.
  - Reconcile shared-cluster DBU against the Slice 2 acceptance query for a sampled cluster.
  - Reconcile pool DBU + pool_total_cost against the Slice 3 split acceptance queries.
  - Assert `idle_cloud_cost >= 0` over a 30-day sample and report the floor-fire rate.
- After deploy, follow the post-deployment monitoring workflow from `CLAUDE.md` (60-second `dba_logz.py` watch + `dba_client.py` smoke tests on the new endpoints).

## Format / lint

- Run `./fix.sh` before each slice's commit.
- Run `ReadLints` on touched files.
