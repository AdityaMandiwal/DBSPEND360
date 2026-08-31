import { CLOUD_PARTIAL_COVERAGE_NOTE } from '@/lib/cloud-coverage-display';

export interface CostCoverageMixValues {
  totalSpend: number;
  coveredCloudCost: number;
  coveredDatabricksCost: number;
  uncoveredCloudCost: number;
  uncoveredDatabricksCost: number;
}

interface CostCoverageMixProps extends CostCoverageMixValues {
  cloudLabel: string;
  formatCurrency: (amount: number) => string;
  compact?: boolean;
}

const percent = (part: number, whole: number) =>
  whole > 0 ? (part / whole) * 100 : 0;

export function CostCoverageMix({
  totalSpend,
  coveredCloudCost,
  coveredDatabricksCost,
  uncoveredCloudCost,
  uncoveredDatabricksCost,
  cloudLabel,
  formatCurrency,
  compact = false,
}: CostCoverageMixProps) {
  const hasUncovered = uncoveredCloudCost > 0 || uncoveredDatabricksCost > 0;
  const coveredSpend = coveredCloudCost + coveredDatabricksCost;
  const rows = hasUncovered
    ? [
        {
          label: `Covered ${cloudLabel.toLowerCase()}`,
          value: coveredCloudCost,
          pct: percent(coveredCloudCost, coveredSpend),
          pctLabel: 'of covered spend',
          color: 'bg-blue-500',
        },
        {
          label: 'Covered Databricks (DBU)',
          value: coveredDatabricksCost,
          pct: percent(coveredDatabricksCost, coveredSpend),
          pctLabel: 'of covered spend',
          color: 'bg-red-500',
        },
        {
          label: 'Uncovered DBU',
          value: uncoveredDatabricksCost,
          pct: percent(uncoveredDatabricksCost, totalSpend),
          pctLabel: 'of total · outside cloud billing scope',
          color: 'bg-amber-500',
        },
        ...(uncoveredCloudCost > 0
          ? [
              {
                label: 'Uncovered cloud (partial)',
                value: uncoveredCloudCost,
                pct: percent(uncoveredCloudCost, totalSpend),
                pctLabel: 'of total · partial cloud billing data',
                color: 'bg-amber-300',
              },
            ]
          : []),
      ]
    : [
        {
          label: cloudLabel,
          value: coveredCloudCost,
          pct: percent(coveredCloudCost, coveredSpend),
          pctLabel: 'of total',
          color: 'bg-blue-500',
        },
        {
          label: 'Databricks (DBU)',
          value: coveredDatabricksCost,
          pct: percent(coveredDatabricksCost, coveredSpend),
          pctLabel: 'of total',
          color: 'bg-red-500',
        },
      ];

  return (
    <div className={compact ? 'space-y-1.5' : 'space-y-3'}>
      {rows.map((row) => (
        <div
          key={row.label}
          className="flex items-center justify-between gap-3"
        >
          <div className="flex min-w-0 items-center gap-2">
            <div className={`h-3 w-3 shrink-0 rounded-full ${row.color}`} />
            <span
              className={compact ? 'truncate text-xs' : 'text-sm font-medium'}
            >
              {row.label}
            </span>
          </div>
          <div className="shrink-0 text-right">
            <div
              className={compact ? 'text-xs font-semibold' : 'font-semibold'}
            >
              {formatCurrency(row.value)}
            </div>
            <div className="text-[11px] text-muted-foreground">
              {row.pct.toFixed(1)}% {row.pctLabel}
            </div>
          </div>
        </div>
      ))}
      <div className="flex h-2 w-full overflow-hidden rounded-full bg-muted">
        {rows.map((row) => (
          <div
            key={row.label}
            className={row.color}
            style={{ width: `${percent(row.value, totalSpend)}%` }}
          />
        ))}
      </div>
      {uncoveredCloudCost > 0 && (
        <p className="text-[11px] leading-snug text-muted-foreground">
          {CLOUD_PARTIAL_COVERAGE_NOTE} DBU on these rows is complete.
        </p>
      )}
    </div>
  );
}
