/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * Per-day cost contribution within a pipeline grouping.
 *
 * Drill-down sub-row inside `GroupedPipeline.days`. The rollup is at product
 * grain (plan §3.3), so the §5.2 read sums across `billing_origin_product`
 * within each `usage_date` before the service nests it here — the UI still
 * sees exactly one row per pipeline-day. `cost_basis` is collapsed to one
 * label for the day ('partial' when the day straddles full + dbu_only).
 * `cloud_cost` is reserved for v2 and is always None in v1; `total_cost` is
 * plumbed straight through from the SQL projection rather than computed.
 */
export type PipelineDailySpend = {
    usage_date: string;
    databricks_cost: number;
    cost_basis: string;
    cloud_cost?: (number | null);
    total_cost?: number;
};

