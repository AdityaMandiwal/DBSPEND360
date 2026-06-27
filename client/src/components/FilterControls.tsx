import { useState, useEffect, useRef } from 'react';
import { Search, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { DateRange } from '@/types/job-spend';
import { useDatePresets } from '@/hooks/useJobSpends';
import { cn, formatCalendarDate, isInvalidDateRange } from '@/lib/utils';
import { AlertTriangle } from 'lucide-react';

interface FilterControlsProps {
  dateRange: DateRange;
  onDateRangeChange: (dateRange: DateRange) => void;
  jobFilter: string;
  onJobFilterChange: (filter: string) => void;
  // True while the table is fetching results for the committed search term.
  isSearching?: boolean;
}

export const FilterControls = ({
  dateRange,
  onDateRangeChange,
  jobFilter,
  onJobFilterChange,
  isSearching = false,
}: FilterControlsProps) => {
  const { data: presets } = useDatePresets();
  const [localFilter, setLocalFilter] = useState(jobFilter);
  // Tracks the debounce window so the spinner appears on the first keystroke,
  // before the request is even fired (the table query only starts after 300ms).
  const [pendingSearch, setPendingSearch] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    setLocalFilter(jobFilter);
  }, [jobFilter]);

  const handleFilterChange = (value: string) => {
    setLocalFilter(value);
    setPendingSearch(true);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      onJobFilterChange(value);
      setPendingSearch(false);
    }, 300);
  };

  // Show feedback during the debounce wait and while the request is in flight.
  const showSearchSpinner = pendingSearch || isSearching;

  useEffect(() => {
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
  }, []);

  const handlePresetClick = (preset: { start_date: string; end_date: string }) => {
    onDateRangeChange({
      start_date: preset.start_date,
      end_date: preset.end_date,
    });
  };

  const dateRangeInvalid = isInvalidDateRange(dateRange.start_date, dateRange.end_date);

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      {/* Date Range Controls */}
      <div className="space-y-4">
        <Label className="text-sm font-semibold">Date Range</Label>

        {/* Date Range Presets */}
        {presets && (
          <div className="flex flex-wrap gap-2">
            {Object.entries(presets).map(([key, preset]) => (
              <Button
                key={key}
                variant="outline"
                size="sm"
                onClick={() => handlePresetClick(preset)}
                className={cn(
                  "text-xs",
                  dateRange.start_date === preset.start_date &&
                  dateRange.end_date === preset.end_date &&
                  "bg-blue-50 border-blue-200 text-blue-700 dark:bg-blue-500/15 dark:border-blue-500/40 dark:text-blue-300"
                )}
              >
                {preset.label}
              </Button>
            ))}
          </div>
        )}

        {/* Custom Date Range Inputs */}
        <div className="space-y-2">
          <div className="grid grid-cols-2 gap-2">
            <div>
              <Label htmlFor="start-date" className="text-sm font-medium">Start Date</Label>
              <Input
                id="start-date"
                type="date"
                value={dateRange.start_date}
                onChange={(e) => onDateRangeChange({
                  start_date: e.target.value,
                  end_date: dateRange.end_date
                })}
                className="mt-1"
              />
            </div>
            <div>
              <Label htmlFor="end-date" className="text-sm font-medium">End Date</Label>
              <Input
                id="end-date"
                type="date"
                value={dateRange.end_date}
                onChange={(e) => onDateRangeChange({
                  start_date: dateRange.start_date,
                  end_date: e.target.value
                })}
                aria-invalid={dateRangeInvalid}
                className={cn("mt-1", dateRangeInvalid && "border-red-500 focus-visible:ring-red-500")}
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

      {/* Job Filter Controls */}
      <div className="space-y-4">
        <Label htmlFor="job-search" className="text-sm font-semibold">Search Jobs</Label>

        <div className="relative">
          <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-muted-foreground" aria-hidden="true" />
          <Input
            id="job-search"
            placeholder="Search by job name or ID..."
            value={localFilter}
            onChange={(e) => handleFilterChange(e.target.value)}
            className="pl-10 pr-10"
          />
          {showSearchSpinner && (
            <span
              className="absolute right-3 top-1/2 -translate-y-1/2 flex items-center justify-center"
              aria-hidden="true"
            >
              <Loader2 className="h-4 w-4 animate-spin text-blue-600" />
            </span>
          )}
        </div>

        {/* Filter Summary */}
        <div className="text-xs text-muted-foreground space-y-1">
          {showSearchSpinner && (
            <div className="flex items-center gap-1.5 text-blue-600" aria-live="polite">
              <Loader2 className="h-3 w-3 animate-spin" />
              <span>Searching jobs…</span>
            </div>
          )}
          <div>
            <strong>Date Range:</strong> {formatCalendarDate(dateRange.start_date)} to {formatCalendarDate(dateRange.end_date)}
          </div>
          {jobFilter && (
            <div>
              <strong>Search:</strong> "{jobFilter}"
            </div>
          )}
        </div>
      </div>
    </div>
  );
};