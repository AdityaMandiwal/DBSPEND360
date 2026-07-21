// Shared display helpers for the All-Purpose Clusters tab cloud (EC2/EBS) cost.
//
// Honesty convention (plan_all_purpose_cloud_null_honesty.md §3, mirroring
// decision #3 in plan_pool_pipeline_ec2_cost.md): `cloud_cost` is kept NULL
// when the value is unknown / not attributable to the cluster, and `0.0` only
// for a genuine zero. A NULL is rendered as "—" with the tooltip below — never
// a misleading bare "$0.00".
//
// A NULL happens when no cluster-tagged EC2/EBS row matched the cluster-day:
//   - the cluster ran on an instance pool, where AWS tags machines with
//     DatabricksInstancePoolId (not ClusterId), so the cluster-keyed Cost
//     Explorer has nothing — the machine cost lives on the Instance Pools tab; or
//   - Cost Explorer data for the cluster simply hasn't landed yet.

export const ALL_PURPOSE_CLOUD_MISSING_NOTE =
  'EC2/EBS cost is not attributed to this cluster. It may run on an instance ' +
  'pool (machine cost is shown on the Instance Pools tab) or its Cost Explorer ' +
  "data hasn't landed yet.";

export {
  CLOUD_NOT_COVERED_LABEL,
  CLOUD_NOT_COVERED_NOTE,
} from '@/lib/cloud-coverage-display';
