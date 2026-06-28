// Shared display helpers for the Instance Pools tab cloud VM cost.
//
// CP8 (plan_pool_pipeline_ec2_cost.md §4.4 / §5) turns on pool VM cost on AWS;
// plan_pool_pipeline_azure_cost.md (AZ-CP2/AZ-CP4) ports it to Azure. The
// wording is provider-neutral because `DatabricksInstancePoolId` is the pool
// tag on both clouds. Two honesty rules drive the "—" tooltips so a missing
// value is never read as a misleading bare $0 (decision #3 — `cloud_cost` is
// kept NULL for "unknown" and `0.0` only for genuine zero):
//
//   - A pool-DAY with no pool-tag cloud row yet → "unavailable" (cloud cost
//     report lag or the `DatabricksInstancePoolId` tag not yet flowing to
//     billing).
//   - A per-CLUSTER row inside the drill-down is always "—": pool VM cost is
//     pool-level, tracked on the synthesized `__pool_overhead__` row, and is
//     not attributable to a specific attached cluster (cloud billing tags pool
//     instances with `DatabricksInstancePoolId`, not `ClusterId`).

// §5 note for a pool/day cloud cell whose value is NULL (data not landed).
export const POOL_CLOUD_MISSING_NOTE =
  'Pool VM cost unavailable — confirm the DatabricksInstancePoolId tag is ' +
  'enabled and the cloud cost report has caught up.';

// §4.4 / §5 note for every per-cluster cloud cell inside a pool's day
// drill-down (always "—").
export const POOL_PER_CLUSTER_CLOUD_NOTE =
  'Pool VM cost is tracked at the pool level, not per attached cluster ' +
  '(cloud billing tags pool instances with DatabricksInstancePoolId, not ' +
  'ClusterId).';
