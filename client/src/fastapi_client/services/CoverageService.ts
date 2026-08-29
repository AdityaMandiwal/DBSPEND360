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
     * When a date range is supplied, excluded-workspace and excluded-DBU values
     * are scoped to that same inclusive window so they reconcile with tab KPIs.
     * @param startDate
     * @param endDate
     * @returns CoverageSummaryResponse Successful Response
     * @throws ApiError
     */
    public static getCoverageSummaryApiCoverageGet(
        startDate?: (string | null),
        endDate?: (string | null),
    ): CancelablePromise<CoverageSummaryResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/coverage',
            query: {
                'start_date': startDate,
                'end_date': endDate,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
