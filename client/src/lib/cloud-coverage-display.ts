// Shared cloud-cost cell labeling for subscription-coverage (all tabs).
//
// Distinguishes two empty states:
//   - workspace_covered === false  → "Not covered" (cross-subscription gap)
//   - workspace_covered === true && value == null → "—" (pool/serverless/not landed)

export const CLOUD_NOT_COVERED_LABEL = 'Not covered';

export const CLOUD_NOT_COVERED_NOTE =
  "Cloud (VM) cost isn't available for this workspace — it runs in a different Azure " +
  'subscription than the one DBSpend360 ingests. The DBU cost shown is complete.';

export type CloudCostDisplay =
  | { kind: 'value'; amount: number }
  | { kind: 'missing'; note: string }
  | { kind: 'not-covered'; note: string };

/** Resolve how to render a cloud-cost cell from coverage + value. */
export function resolveCloudCostDisplay(
  value: number | null | undefined,
  workspaceCovered: boolean | undefined,
  missingNote: string,
): CloudCostDisplay {
  if (workspaceCovered === false && (value == null || value === undefined)) {
    return { kind: 'not-covered', note: CLOUD_NOT_COVERED_NOTE };
  }
  if (value == null) {
    return { kind: 'missing', note: missingNote };
  }
  return { kind: 'value', amount: value };
}
