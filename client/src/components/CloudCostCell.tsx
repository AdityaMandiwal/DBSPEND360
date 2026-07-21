import { CLOUD_NOT_COVERED_LABEL, resolveCloudCostDisplay } from '@/lib/cloud-coverage-display';

const currencyFormatter = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

interface CloudCostCellProps {
  value: number | null | undefined;
  workspaceCovered?: boolean;
  missingNote: string;
  className?: string;
}

/** Shared cloud-cost cell renderer for all cost tabs. */
export function CloudCostCell({
  value,
  workspaceCovered = true,
  missingNote,
  className,
}: CloudCostCellProps) {
  const display = resolveCloudCostDisplay(value, workspaceCovered, missingNote);

  if (display.kind === 'value') {
    return <span className={className}>{currencyFormatter.format(display.amount)}</span>;
  }

  if (display.kind === 'not-covered') {
    return (
      <span
        className={`cursor-help font-medium text-amber-700 dark:text-amber-300 ${className ?? ''}`}
        title={display.note}
        aria-label={display.note}
      >
        {CLOUD_NOT_COVERED_LABEL}
      </span>
    );
  }

  return (
    <span
      className={`cursor-help text-muted-foreground ${className ?? ''}`}
      title={display.note}
      aria-label={display.note}
    >
      —
    </span>
  );
}
