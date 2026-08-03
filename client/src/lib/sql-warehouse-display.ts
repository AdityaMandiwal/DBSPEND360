// Shared display helpers for the SQL Warehouses tab.
//
// `warehouse_type` (CLASSIC / PRO / SERVERLESS) is rendered as a badge in the
// KPI strip, the By-Warehouse table, and the details modal. Centralising the
// colour map keeps the badge identical across all three surfaces. The palette
// mirrors `./pipeline-display.ts` so the tabs feel like one app.

const WAREHOUSE_TYPE_CLASSES: Record<string, string> = {
  SERVERLESS:
    'bg-green-100 text-green-700 dark:bg-green-500/15 dark:text-green-300',
  PRO: 'bg-blue-100 text-blue-700 dark:bg-blue-500/15 dark:text-blue-300',
  CLASSIC:
    'bg-orange-100 text-orange-700 dark:bg-orange-500/15 dark:text-orange-300',
};

// Unknown / missing types still render coherently instead of unstyled — the
// common case here, since most warehouses carry no metadata snapshot.
const WAREHOUSE_TYPE_FALLBACK =
  'bg-slate-100 text-slate-700 dark:bg-slate-500/15 dark:text-slate-300';

export const warehouseTypeBadgeClasses = (type?: string | null): string =>
  WAREHOUSE_TYPE_CLASSES[type?.toUpperCase() ?? ''] ?? WAREHOUSE_TYPE_FALLBACK;

export const warehouseTypeLabel = (type?: string | null): string => {
  switch (type?.toUpperCase()) {
    case 'SERVERLESS':
      return 'Serverless';
    case 'PRO':
      return 'Pro';
    case 'CLASSIC':
      return 'Classic';
    default:
      return type ?? 'Unknown';
  }
};

// NaN-safe USD formatter. A missing/undefined numeric field would otherwise
// render "$NaN"; guard so non-finite values fall back to $0.00.
const usdFormatter = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

export const formatCurrency = (n: number): string =>
  usdFormatter.format(Number.isFinite(n) ? n : 0);
