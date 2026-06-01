/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * Cloud platform configuration information.
 *
 * Also carries the dashboard-tab feature flags so the frontend can render
 * the tab list conditionally without a second round-trip. Both
 * `enable_shared_clusters_tab` / `enable_instance_pools_tab` default to
 * True; flip them off in `app.<env>.config` to hide the new tabs while
 * the backing data backfill is still running.
 */
export type CloudPlatformInfo = {
  platform: string;
  compute_service: string;
  compute_display_name: string;
  platform_display_name: string;
  enable_shared_clusters_tab?: boolean;
  enable_instance_pools_tab?: boolean;
};
