/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * LLM-generated configuration analysis for an instance pool.
 *
 * Returned by `/api/instance-pools/{id}/analyze`. The analysis text is
 * expected to include the v1 cloud-cost caveat (plan §10 risks row, CP7
 * exit criterion #4) since idle and active cloud VM cost is invisible to
 * v1 (plan §3.2). The output structure mirrors `ClusterAnalysis`'s
 * config-shape sections (Overall Rating / Right-Sizing / Cost Savings /
 * Idle Waste Risk / Configuration Gaps) rather than the run-cost trend
 * structure used by `CostAnalysis`.
 */
export type InstancePoolAnalysis = {
    instance_pool_id: string;
    analysis: string;
    timestamp?: string;
};

