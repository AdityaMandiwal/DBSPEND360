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
          className={
            compact
              ? 'space-y-0.5'
              : 'flex items-center justify-between gap-3'
          }
        >
          <div
            className={
              compact
                ? 'flex items-start justify-between gap-2'
                : 'flex min-w-0 items-center gap-2'
            }
          >
            <div className="flex min-w-0 items-start gap-2">
              <div
                className={`shrink-0 rounded-full ${row.color} ${
                  compact ? 'mt-1 h-2.5 w-2.5' : 'h-3 w-3'
                }`}
              />
              <span
                className={
                  compact
                    ? 'text-xs font-medium leading-tight'
                    : 'text-sm font-medium'
                }
              >
                {row.label}
              </span>
            </div>
            {compact && (
              <div className="shrink-0 text-xs font-semibold">
                {formatCurrency(row.value)}
              </div>
            )}
          </div>
          {!compact && (
            <div className="shrink-0 text-right">
              <div className="font-semibold">{formatCurrency(row.value)}</div>
              <div className="text-[11px] text-muted-foreground">
                {row.pct.toFixed(1)}% {row.pctLabel}
              </div>
            </div>
          )}
          {compact && (
            <div className="pl-[18px] text-[11px] leading-tight text-muted-foreground">
              {row.pct.toFixed(1)}% {row.pctLabel}
            </div>
          )}
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
          {compact
            ? 'Cloud cost is partial because some activity is outside the configured billing scope. DBU cost is complete.'
            : `${CLOUD_PARTIAL_COVERAGE_NOTE} DBU on these rows is complete.`}
        </p>
      )}
    </div>
  );
}
