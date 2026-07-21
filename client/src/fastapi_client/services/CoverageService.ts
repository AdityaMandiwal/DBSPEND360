/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { CoverageSummaryResponse } from '../models/CoverageSummaryResponse';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class CoverageService {
    /**
     * Get Coverage Summary
     * Return the full subscription-coverage map for banners and KPIs.
     *
     * Single param-less call; the client fetches once and each tab reads its
     * own key from `excluded_dbu_by_tab`.
     * @returns CoverageSummaryResponse Successful Response
     * @throws ApiError
     */
    public static getCoverageSummaryApiCoverageGet(): CancelablePromise<CoverageSummaryResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/coverage',
        });
    }
}
