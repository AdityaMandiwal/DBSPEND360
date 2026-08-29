// Filter controls for the Pipeline Compute tab.
//
// Parallels `InstancePoolFilterControls.tsx` (same date presets + 300ms
// debounce-on-search), with one addition specific to this tab: **workload-type
// filter chips** (plan §3.1 / §4.1 / CP10).
//
// The chip set is sourced from the *unfiltered* summary's `workload_breakdown`
// keys (sorted by $ descending) so it always reflects exactly the workloads
// present in the window — and stays stable as the user toggles chips (the chip
// list itself is derived from the unfiltered breakdown so options never
// disappear under you). The chips are an OR (server-side `IN (...)`) include
// filter: an empty selection means "all"; selecting chips includes only those
// types, and selecting MORE chips shows MORE rows (plan §3.1 / §7.3). Spend is
// never hidden — it always stays attributed under its own type.
//
// The search box hits the `search` query param on `/api/pipelines/grouped`,
// which matches pipeline name (case-insensitive substring), pipeline_id
// (exact), and created_by (case-insensitive substring) — plan §5.1.

import { useEffect, useMemo, useRef, useState } from 'react';
import { Search, AlertTriangle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import type { DateRange } from '@/types/job-spend';
import { useDatePresets } from '@/hooks/useJobSpends';
import { usePipelineSummary } from '@/hooks/usePipelines';
import { workloadBadgeClasses } from '@/lib/pipeline-display';
import { cn, formatCalendarDate, isInvalidDateRange } from '@/lib/utils';

interface PipelineFilterControlsProps {
  dateRange: DateRange;
  onDateRangeChange: (dateRange: DateRange) => void;
  searchTerm: string;
  onSearchTermChange: (filter: string) => void;
  selectedWorkloads: string[];
  onSelectedWorkloadsChange: (workloads: string[]) => void;
}

export const PipelineFilterControls = ({
  dateRange,
  onDateRangeChange,
  searchTerm,
  onSearchTermChange,
  selectedWorkloads,
  onSelectedWorkloadsChange,
}: PipelineFilterControlsProps) => {
  const { data: presets } = useDatePresets();
  const [localFilter, setLocalFilter] = useState(searchTerm);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Unfiltered summary purely to source the chip list (so options never
  // vanish as chips are toggled). React Query dedupes this against the
  // unfiltered summary used elsewhere.
  const { data: summary } = usePipelineSummary(dateRange);

  const availableWorkloads = useMemo(() => {
    if (!summary) return [];
    return Object.entries(summary.workload_breakdown)
      .sort((a, b) => b[1] - a[1])
      .map(([workload]) => workload);
  }, [summary]);

  useEffect(() => {
    setLocalFilter(searchTerm);
  }, [searchTerm]);

  const handleFilterChange = (value: string) => {
    setLocalFilter(value);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => onSearchTermChange(value), 300);
  };

  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, []);

  const handlePresetClick = (preset: {
    start_date: string;
    end_date: string;
  }) => {
    onDateRangeChange({
      start_date: preset.start_date,
      end_date: preset.end_date,
    });
  };

  const toggleWorkload = (workload: string) => {
    if (selectedWorkloads.includes(workload)) {
      onSelectedWorkloadsChange(
        selectedWorkloads.filter((w) => w !== workload),
      );
    } else {
      onSelectedWorkloadsChange([...selectedWorkloads, workload]);
    }
  };

  const dateRangeInvalid = isInvalidDateRange(dateRange.start_date, dateRange.end_date);

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="space-y-4">
          <Label className="text-sm font-semibold">Date Range</Label>

          {presets && (
            <div className="flex flex-wrap gap-2">
              {Object.entries(presets).map(([key, preset]) => (
                <Button
                  key={key}
                  variant="outline"
                  size="sm"
                  onClick={() => handlePresetClick(preset)}
                  className={cn(
                    'text-xs',
                    dateRange.start_date === preset.start_date &&
                      dateRange.end_date === preset.end_date &&
                      'bg-blue-50 border-blue-200 text-blue-700 dark:bg-blue-500/15 dark:border-blue-500/40 dark:text-blue-300',
                  )}
                >
                  {preset.label}
                </Button>
              ))}
            </div>
          )}

          <div className="space-y-2">
            <div className="grid grid-cols-2 gap-2">
              <div>
                <Label htmlFor="pl-start-date" className="text-sm font-medium">
                  Start Date
                </Label>
                <Input
                  id="pl-start-date"
                  type="date"
                  value={dateRange.start_date}
                  onChange={(e) =>
                    onDateRangeChange({
                      start_date: e.target.value,
                      end_date: dateRange.end_date,
                    })
                  }
                  className="mt-1"
                />
              </div>
              <div>
                <Label htmlFor="pl-end-date" className="text-sm font-medium">
                  End Date
                </Label>
                <Input
                  id="pl-end-date"
                  type="date"
                  value={dateRange.end_date}
                  onChange={(e) =>
                    onDateRangeChange({
                      start_date: dateRange.start_date,
                      end_date: e.target.value,
                    })
                  }
                  aria-invalid={dateRangeInvalid}
                  className={cn('mt-1', dateRangeInvalid && 'border-red-500 focus-visible:ring-red-500')}
                />
              </div>
            </div>
            {dateRangeInvalid && (
              <div className="flex items-center gap-1.5 text-xs text-red-600" role="alert">
                <AlertTriangle className="h-3.5 w-3.5" aria-hidden="true" />
                <span>Start date must be on or before the end date.</span>
              </div>
            )}
          </div>
        </div>

        <div className="space-y-4">
          <Label htmlFor="pl-search" className="text-sm font-semibold">Search Pipelines</Label>

          <div className="relative">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-muted-foreground" aria-hidden="true" />
            <Input
              id="pl-search"
              placeholder="Search by pipeline name, pipeline ID, or creator..."
              value={localFilter}
              onChange={(e) => handleFilterChange(e.target.value)}
              className="pl-10"
            />
          </div>

          <div className="text-xs text-muted-foreground space-y-1">
            <div>
              <strong>Date Range:</strong>{' '}
              {formatCalendarDate(dateRange.start_date)} to{' '}
              {formatCalendarDate(dateRange.end_date)}
            </div>
            {searchTerm && (
              <div>
                <strong>Search:</strong> "{searchTerm}"
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Workload-type filter chips — an OR (IN) include filter: empty
          selection = all workloads; selecting chips includes only those
          types, and selecting more includes more. Spend is never hidden —
          it stays attributed under its own type (plan §3.1 / §7.3). */}
      {availableWorkloads.length > 0 && (
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <Label className="text-sm font-semibold">Workload Type</Label>
            {selectedWorkloads.length > 0 && (
              <Button
                variant="ghost"
                size="sm"
                className="h-6 text-xs"
                onClick={() => onSelectedWorkloadsChange([])}
              >
                Clear ({selectedWorkloads.length})
              </Button>
            )}
          </div>
          <div
            className="flex flex-wrap gap-2"
            role="group"
            aria-label="Pipeline workload type filters"
          >
            {availableWorkloads.map((workload) => {
              const isSelected = selectedWorkloads.includes(workload);
              return (
                <button
                  key={workload}
                  type="button"
                  onClick={() => toggleWorkload(workload)}
                  aria-pressed={isSelected}
                  className="focus:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded-full"
                >
                  <Badge
                    variant="secondary"
                    className={cn(
                      'cursor-pointer text-xs transition-opacity',
                      workloadBadgeClasses(workload),
                      selectedWorkloads.length > 0 &&
                        !isSelected &&
                        'opacity-40',
                      isSelected && 'ring-2 ring-offset-1 ring-current',
                    )}
                  >
                    {workload}
                  </Badge>
                </button>
              );
            })}
          </div>
          <p className="text-xs text-muted-foreground">
            {selectedWorkloads.length === 0
              ? 'Showing all workload types. Select one or more chips to include only those types.'
              : 'Including the selected workload type(s) — chips are an OR filter, so selecting more shows more. Spend always stays attributed under its own type.'}
          </p>
        </div>
      )}
    </div>
  );
};
