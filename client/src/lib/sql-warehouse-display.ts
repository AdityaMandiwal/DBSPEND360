// Shared display helpers for the SQL Warehouses tab.
//
// `warehouse_type` (CLASSIC / PRO / SERVERLESS) is rendered as a badge in the
// KPI strip, the By-Warehouse table, and the details modal. Centralising the
// colour map keeps the badge identical across all three surfaces. The palette
// mirrors `./pipeline-display.ts` so the tabs feel like one app.

const WAREHOUSE_TYPE_CLASSES: Record<string, string> = {
  SERVERLESS:
    "bg-green-100 text-green-700 dark:bg-green-500/15 dark:text-green-300",
  PRO: "bg-blue-100 text-blue-700 dark:bg-blue-500/15 dark:text-blue-300",
  CLASSIC:
    "bg-orange-100 text-orange-700 dark:bg-orange-500/15 dark:text-orange-300",
};

// Unknown / missing types still render coherently instead of unstyled — the
// common case here, since most warehouses carry no metadata snapshot.
const WAREHOUSE_TYPE_FALLBACK =
  "bg-slate-100 text-slate-700 dark:bg-slate-500/15 dark:text-slate-300";

export const warehouseTypeBadgeClasses = (type?: string | null): string =>
  WAREHOUSE_TYPE_CLASSES[type?.toUpperCase() ?? ""] ?? WAREHOUSE_TYPE_FALLBACK;

// Presentation helper for unknown warehouse types (e.g. `REAL_TIME` from
// `system.compute.warehouses`). We don't want to leak the raw uppercase-and-
// underscored SKU-shape into the UI, but hard-coding every possible value
// would drift as new SKUs land, so anything outside the curated set falls
// through to a simple title-case transform:
//   REAL_TIME  -> Real Time
//   real-time  -> Real Time
//   fooBar     -> Foobar
const toTitleCase = (raw: string): string =>
  raw
    .toLowerCase()
    .split(/[_\s-]+/)
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");

export const warehouseTypeLabel = (type?: string | null): string => {
  switch (type?.toUpperCase()) {
    case "SERVERLESS":
      return "Serverless";
    case "PRO":
      return "Pro";
    case "CLASSIC":
      return "Classic";
    default:
      if (!type || !type.trim()) return "Unknown";
      return toTitleCase(type);
  }
};

export const warehouseCostBasis = (
  type?: string | null,
): "full" | "dbu_only" | "unknown" => {
  const normalized = type?.trim().toUpperCase();
  if (!normalized) return "unknown";
  if (normalized === "CLASSIC" || normalized.includes("PRO")) return "dbu_only";
  return "full";
};

export const warehouseCostBasisLabel = (basis: string): string => {
  if (basis === "full") return "Complete cost";
  if (basis === "dbu_only") return "DBU only";
  return "Cost basis unknown";
};

// NaN-safe USD formatter. A missing/undefined numeric field would otherwise
// render "$NaN"; guard so non-finite values fall back to $0.00.
const usdFormatter = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

export const formatCurrency = (n: number): string =>
  usdFormatter.format(Number.isFinite(n) ? n : 0);
