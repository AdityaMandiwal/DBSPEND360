/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * LLM-generated configuration analysis for an instance pool.
 *
 * Returned by `/api/instance-pools/{id}/analyze`. The summary contains
 * ClusterId-free idle/warm pool cloud cost and explicitly discloses that
 * active pool-backed VM cost remains on the Job or All-Purpose lens. The
 * output structure mirrors `ClusterAnalysis`'s
 * config-shape sections (Overall Rating / Right-Sizing / Cost Savings /
 * Idle Waste Risk / Configuration Gaps) rather than the run-cost trend
 * structure used by `CostAnalysis`.
 */
export type InstancePoolAnalysis = {
    instance_pool_id: string;
    analysis: string;
    timestamp?: string;
};

