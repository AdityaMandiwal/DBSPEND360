/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * LLM-generated cost analysis for a pipeline.
 *
 * Returned by `/api/pipelines/{id}/analyze`. The analysis is fed
 * workload, compute, DBU, cloud, and cloud-coverage context so it discloses
 * missing cloud VM cost only when coverage is incomplete.
 */
export type PipelineAnalysis = {
    pipeline_id: string;
    analysis: string;
    timestamp?: string;
};

