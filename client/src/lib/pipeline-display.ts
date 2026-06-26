// Shared display helpers for the Pipeline Compute tab.
//
// `workload_type` is a first-class dimension (plan §3.1) rendered as a badge
// in three places — the KPI strip, the By-Pipeline table, and the details
// modal. Centralising the colour map here keeps the badge visually identical
// across all three surfaces and means a new workload type only needs one
// edit. Unknown/new workloads (the "never dropped" raw-value fallback —
// plan §3.1) get a neutral grey so they still render coherently.
//
// `cost_basis` (full / dbu_only / partial — plan §3.2) drives the per-row
// honesty caveat; the caption helpers below produce the exact tooltip text
// the plan specifies so the wording stays consistent between the table icon
// and the modal banner.

// Tailwind class set per known workload type. Light + dark variants mirror
// the `PoolStateBadge` palette so the four tabs feel like one app.
const WORKLOAD_BADGE_CLASSES: Record<string, string> = {
  'DLT Pipeline':
    'bg-blue-100 text-blue-700 dark:bg-blue-500/15 dark:text-blue-300',
  'DBSQL Materialized View':
    'bg-violet-100 text-violet-700 dark:bg-violet-500/15 dark:text-violet-300',
  'Online Table':
    'bg-teal-100 text-teal-700 dark:bg-teal-500/15 dark:text-teal-300',
  'Vector Search':
    'bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300',
  'Model Serving':
    'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300',
  'AI Functions':
    'bg-fuchsia-100 text-fuchsia-700 dark:bg-fuchsia-500/15 dark:text-fuchsia-300',
};

const WORKLOAD_FALLBACK_CLASSES =
  'bg-slate-100 text-slate-700 dark:bg-slate-500/15 dark:text-slate-300';

export const workloadBadgeClasses = (workloadType: string): string =>
  WORKLOAD_BADGE_CLASSES[workloadType] ?? WORKLOAD_FALLBACK_CLASSES;

// `compute_mode` (serverless / classic / mixed — plan §3.1) badge palette.
const COMPUTE_MODE_CLASSES: Record<string, string> = {
  serverless:
    'bg-green-100 text-green-700 dark:bg-green-500/15 dark:text-green-300',
  classic:
    'bg-orange-100 text-orange-700 dark:bg-orange-500/15 dark:text-orange-300',
  mixed:
    'bg-slate-100 text-slate-700 dark:bg-slate-500/15 dark:text-slate-300',
};

export const computeModeClasses = (mode: string): string =>
  COMPUTE_MODE_CLASSES[mode] ?? COMPUTE_MODE_CLASSES.mixed;

// Per plan §3.2 the `$` carries a caveat only when the number excludes cloud
// VM cost (classic) — `full` (all serverless) is the complete cost and gets
// no icon. Returns null for `full` so callers can branch on truthiness.
export const costBasisCaveat = (costBasis?: string | null): string | null => {
  switch (costBasis) {
    case 'dbu_only':
      return 'Databricks DBU only — excludes cloud VM cost';
    case 'partial':
      return 'Partly DBU-only — classic portion excludes cloud VM cost';
    default:
      // 'full' (or any unexpected value) → complete cost, no caveat.
      return null;
  }
};

// §5 "data not present" notes for the EC2/EBS cloud cell (CP3). The cloud
// number is kept NULL when unknown vs `0.0` only when genuinely zero
// (decision #3), so the UI can tell "we don't have it yet" from a real $0.
// A NULL cloud cell renders "—" + one of these typed reasons depending on
// whether the row/day is serverless (the absence is by-design) or classic
// (the absence is a data gap — Cost Explorer lag or an untagged cluster).
export const cloudMissingNote = (isServerless: boolean): string =>
  isServerless
    ? 'Serverless — EC2 cost is bundled into the serverless DBU rate; no separate VM line.'
    : 'EC2 cost not yet available for this cluster/day (Cost Explorer lag or untagged cluster).';

// Badge/tooltip for a `mixed` row that DOES carry a cloud number: the figure
// covers the classic portion only; the serverless portion has no separate VM
// line (§5).
export const MIXED_CLOUD_NOTE =
  'Classic portion only; serverless portion has no separate VM line.';
