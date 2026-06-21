import { useCloudPlatform } from '@/contexts/CloudPlatformContext';

/**
 * Hard-wired cloud-cost label for AWS-gated render paths.
 *
 * Deliberately NOT derived from `compute_service` ("EC2") or
 * `compute_display_name` ("EC2 Cost"): the config mapping stays "EC2" so
 * `/ EBS` never leaks into LLM prompts or other `compute_service` consumers.
 * Every AWS-gated frontend branch references this single const instead of
 * re-typing the literal, so the CI regression grep can mechanically enforce it.
 */
export const AWS_CLOUD_LABEL = 'EC2 / EBS';

/**
 * True only when the active cloud platform is AWS.
 *
 * Drives AWS-specific labels (`AWS_CLOUD_LABEL`) and column dropping. Do NOT
 * use `!useIsAws()` to decide whether to show the segmented breakdown — use
 * `useIsSegmentedPlatform()` for that (positive allowlist; see below).
 */
export function useIsAws(): boolean {
  const { config } = useCloudPlatform();
  return config?.platform === 'AWS';
}

/**
 * Positive allowlist: segmented compute/storage/network is shown ONLY for
 * platforms we know emit a full segmentation. AWS, `Unknown`, and the loading
 * window (`config === null`) all return false → callers fall to the
 * always-correct 2-slice (`cloud_cost` + DBU).
 *
 * Keying segmentation off this (rather than `!isAws`) prevents the config-fetch
 * failure / first-paint `null` window from routing onto the data-shape path,
 * which understates per-segment dollars on runs straddling the deploy date.
 */
export function useIsSegmentedPlatform(): boolean {
  const { config } = useCloudPlatform();
  return config?.platform === 'Azure' || config?.platform === 'GCP';
}
