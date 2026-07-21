import { useState } from 'react';
import { Info, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import { useJobProductBreakdown } from '@/hooks/useJobProductBreakdown';
import type { DateRange } from '@/types/job-spend';

const formatCurrency = (amount: number) =>
  new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount);

const NON_JOB_PRODUCTS = new Set(['MODEL_SERVING', 'AI_FUNCTIONS', 'VECTOR_SEARCH']);

interface DbuProductBreakdownPopoverProps {
  jobId: string;
  dateRange: DateRange;
  storedDbuCost: number;
}

export const DbuProductBreakdownPopover = ({
  jobId,
  dateRange,
  storedDbuCost,
}: DbuProductBreakdownPopoverProps) => {
  const [open, setOpen] = useState(false);
  const { data, isLoading, error } = useJobProductBreakdown(
    jobId,
    { start_date: dateRange.start_date, end_date: dateRange.end_date },
    open,
  );

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="h-6 w-6 shrink-0 text-muted-foreground hover:text-foreground"
          aria-label="View DBU product breakdown"
        >
          <Info className="h-3.5 w-3.5" aria-hidden="true" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-80 p-4" align="end">
        <div className="space-y-3">
          <div>
            <h4 className="font-semibold text-sm">DBU Product Breakdown</h4>
            <p className="text-xs text-muted-foreground mt-1">
              Live estimate from billing usage. Totals may differ from the stored DBU column.
            </p>
          </div>

          {isLoading ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground py-2">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              <span>Loading breakdown…</span>
            </div>
          ) : error ? (
            <p className="text-sm text-red-600">Breakdown unavailable.</p>
          ) : !data || data.items.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No billing usage found for this job in the selected range.
            </p>
          ) : (
            <>
              <div className="space-y-2">
                {data.items.map((item) => {
                  const isNonJob = NON_JOB_PRODUCTS.has(item.billing_origin_product);
                  return (
                    <div
                      key={item.billing_origin_product}
                      className="flex items-center justify-between text-sm gap-3"
                    >
                      <span
                        className={
                          isNonJob && data.has_multiple_products
                            ? 'text-amber-700 font-medium'
                            : 'text-foreground'
                        }
                      >
                        {item.label}
                      </span>
                      <span className="tabular-nums text-muted-foreground whitespace-nowrap">
                        {formatCurrency(item.cost)}
                        <span className="ml-2 w-12 inline-block text-right">
                          {item.percentage.toFixed(1)}%
                        </span>
                      </span>
                    </div>
                  );
                })}
              </div>

              {!data.has_multiple_products &&
                data.items.length === 1 &&
                data.items[0].billing_origin_product === 'JOBS' && (
                  <p className="text-sm text-muted-foreground">
                    100% job compute — no other products.
                  </p>
                )}

              <div className="border-t pt-2 space-y-1 text-sm">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Estimate total</span>
                  <span className="font-medium tabular-nums">
                    {formatCurrency(data.total_cost)}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Stored DBU cost</span>
                  <span className="font-medium tabular-nums">
                    {formatCurrency(data.rollup_databricks_cost ?? storedDbuCost)}
                  </span>
                </div>
              </div>

              {data.unpriced_warning && (
                <p className="text-xs text-amber-700 italic">{data.unpriced_warning}</p>
              )}
            </>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
};
