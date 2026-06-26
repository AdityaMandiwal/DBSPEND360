// Filter controls for the Pipeline Compute tab.
//
// Parallels `InstancePoolFilterControls.tsx` (same date presets + 300ms
// debounce-on-search), with one addition specific to this tab: **workload-type
// filter chips** (plan §3.1 / §4.1 / CP10).
//
// The chip set is sourced from the *unfiltered* summary's `workload_breakdown`
// keys (sorted by $ descending) so it always reflects exactly the workloads
// present in the window — and stays stable as the user toggles chips (toggling
// narrows the table + KPI summary, but the chip list itself is derived from
// the unfiltered breakdown so options never disappear under you). Workload
// chips only *narrow*; they never drop spend (plan §3.1) — an empty selection
// means "all".
//
// The search box hits the `search` query param on `/api/pipelines/grouped`,
// which matches pipeline name (case-insensitive substring), pipeline_id
// (exact), and created_by (case-insensitive substring) — plan §5.1.

import { useEffect, useMemo, useRef, useState } from 'react';
import { Search } from 'lucide-react';
import { format } from 'date-fns';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import type { DateRange } from '@/types/job-spend';
import { useDatePresets } from '@/hooks/useJobSpends';
import { usePipelineSummary } from '@/hooks/usePipelines';
import { workloadBadgeClasses } from '@/lib/pipeline-display';
import { cn } from '@/lib/utils';

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

  const formatDisplayDate = (dateStr: string) => {
    try {
      return format(new Date(dateStr), 'MMM dd, yyyy');
    } catch {
      return dateStr;
    }
  };

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
                  className="mt-1"
                />
              </div>
            </div>
          </div>
        </div>

        <div className="space-y-4">
          <Label className="text-sm font-semibold">Search Pipelines</Label>

          <div className="relative">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Search by pipeline name, pipeline ID, or creator..."
              value={localFilter}
              onChange={(e) => handleFilterChange(e.target.value)}
              className="pl-10"
            />
          </div>

          <div className="text-xs text-muted-foreground space-y-1">
            <div>
              <strong>Date Range:</strong>{' '}
              {formatDisplayDate(dateRange.start_date)} to{' '}
              {formatDisplayDate(dateRange.end_date)}
            </div>
            {searchTerm && (
              <div>
                <strong>Search:</strong> "{searchTerm}"
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Workload-type filter chips — narrow only, never drop spend
          (plan §3.1). Empty selection = all workloads. */}
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
          <div className="flex flex-wrap gap-2">
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
              ? 'Showing all workload types. Click a chip to narrow.'
              : 'Filtering — workload chips narrow the view but never hide spend (it stays attributed under its own type).'}
          </p>
        </div>
      )}
    </div>
  );
};
