# Slice 1 — UI tabification (½–1 day)

[← back to plan index](README.md)

## Frontend changes

- `client/src/components/Dashboard.tsx`: wrap existing content in a shadcn `Tabs` component with three tabs: **Jobs** (current view), **Shared Clusters** (placeholder), **Instance Pools** (placeholder).
- Lift shared state (`dateRange`, eventually filters) into a small `DashboardContext` co-located with `Dashboard.tsx`. `CloudPlatformContext` stays as-is.
- Add `npx shadcn@latest add tabs` if the component isn't already in `client/src/components/ui`.
- New components scaffold (placeholders, will be filled in by later slices):
  - `client/src/components/SharedClustersTab.tsx`
  - `client/src/components/InstancePoolsTab.tsx`
- Move the current JSX (SummaryCards + FilterControls + GroupedJobTable + JobBreakdownModal) into `client/src/components/JobsTab.tsx`.

## Acceptance criteria

- All existing functionality works identically; no regression in Jobs tab.
- Tabs render with shadcn styling; placeholder tabs show a friendly "Coming soon" card.
- No backend changes in this slice.

## Effort

~0.5–1 day
