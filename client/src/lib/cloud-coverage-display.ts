// Shared cloud-cost cell labeling for subscription-coverage (all tabs).
//
// Distinguishes two empty states:
//   - value is present → show it, even when the workspace is outside the
//     configured scope (historical/partial cloud data can still exist)
//   - uncovered + value is null → "Not covered" (cross-subscription gap)
//   - covered + value is null → "—" (pool/serverless/not landed)

export const CLOUD_NOT_COVERED_LABEL = "Not covered";

export const CLOUD_NOT_COVERED_NOTE =
  "Cloud (VM) cost isn't available for this workspace — it is outside the cloud billing " +
  "scope DBSpend360 ingests. The DBU cost shown is complete.";

export const CLOUD_PARTIAL_COVERAGE_NOTE =
  "The displayed cloud cost is available, but this grouping also contains " +
  "workspace activity outside the configured cloud billing scope. Treat the amount as partial.";

export type CloudCostDisplay =
  | { kind: "value"; amount: number; partial: boolean; note?: string }
  | { kind: "missing"; note: string }
  | { kind: "not-covered"; note: string };

/** Resolve how to render a cloud-cost cell from coverage + value. */
export function resolveCloudCostDisplay(
  value: number | null | undefined,
  workspaceCovered: boolean | undefined,
  missingNote: string,
): CloudCostDisplay {
  if (value != null) {
    return workspaceCovered === false
      ? {
          kind: "value",
          amount: value,
          partial: true,
          note: CLOUD_PARTIAL_COVERAGE_NOTE,
        }
      : { kind: "value", amount: value, partial: false };
  }
  if (workspaceCovered === false) {
    return { kind: "not-covered", note: CLOUD_NOT_COVERED_NOTE };
  }
  return { kind: "missing", note: missingNote };
}
