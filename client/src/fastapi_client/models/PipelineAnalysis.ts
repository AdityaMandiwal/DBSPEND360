/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * LLM-generated cost analysis for a pipeline.
 *
 * Returned by `/api/pipelines/{id}/analyze`. The analysis is fed
 * `workload_type` + `cost_basis` context so it never gives confidently-wrong
 * advice on incomplete numbers — it MUST state the DBU-only caveat when
 * `cost_basis != 'full'` and must not recommend cloud-VM changes on numbers
 * it knows are DBU-only (plan §4.1 / CP7).
 */
export type PipelineAnalysis = {
    pipeline_id: string;
    analysis: string;
    timestamp?: string;
};

