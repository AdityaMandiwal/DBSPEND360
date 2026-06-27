/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * LLM-generated configuration analysis for an instance pool.
 *
 * Returned by `/api/instance-pools/{id}/analyze`. As of CP8
 * (plan_pool_pipeline_ec2_cost.md §4.4) pool EC2/EBS cost is in the
 * summary, so the analysis text now carries only the remaining
 * idle-vs-active-split caveat (plan §4.5) rather than the old DBU-only
 * caveat. The output structure mirrors `ClusterAnalysis`'s
 * config-shape sections (Overall Rating / Right-Sizing / Cost Savings /
 * Idle Waste Risk / Configuration Gaps) rather than the run-cost trend
 * structure used by `CostAnalysis`.
 */
export type InstancePoolAnalysis = {
    instance_pool_id: string;
    analysis: string;
    timestamp?: string;
};

