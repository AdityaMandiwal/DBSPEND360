// Filter controls for the All-Purpose tab.
//
// Parallels `FilterControls.tsx` (job-cluster). Same date presets, same
// debounce-on-search pattern. The label/placeholder strings are tuned for
// clusters/owners instead of jobs, and the search box hits the new
// `search` query parameter on `/api/all-purpose/grouped-by-cluster` and
// `/api/all-purpose/grouped-by-user`.

import { useEffect, useRef, useState } from 'react';
import { Search } from 'lucide-react';
import { format } from 'date-fns';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import type { DateRange } from '@/types/job-spend';
import { useDatePresets } from '@/hooks/useJobSpends';
import { cn } from '@/lib/utils';

interface AllPurposeClusterFilterControlsProps {
  dateRange: DateRange;
  onDateRangeChange: (dateRange: DateRange) => void;
  searchTerm: string;
  onSearchTermChange: (filter: string) => void;
  // The two sub-tabs search different fields, so the placeholder/help text
  // is parameterized by the active sub-tab.
  subTab: 'by-cluster' | 'by-user';
}

export const AllPurposeClusterFilterControls = ({
  dateRange,
  onDateRangeChange,
  searchTerm,
  onSearchTermChange,
  subTab,
}: AllPurposeClusterFilterControlsProps) => {
  const { data: presets } = useDatePresets();
  const [localFilter, setLocalFilter] = useState(searchTerm);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    setLocalFilter(searchTerm);
  }, [searchTerm]);

  // Debounce mirror of `FilterControls`'s 300ms — keeps the two tabs
  // feeling identical and avoids one query per keystroke.
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

  const handlePresetClick = (preset: { start_date: string; end_date: string }) => {
    onDateRangeChange({
      start_date: preset.start_date,
      end_date: preset.end_date,
    });
  };

  const formatDisplayDate = (dateStr: string) => {
    try {
      return format(new Date(dateStr), 'MMM dd, yyyy');
    } catch {
      return dateStr;
    }
  };

  const searchPlaceholder =
    subTab === 'by-cluster'
      ? 'Search by cluster name, cluster ID, or owner...'
      : 'Search by user (owner) ID...';
  const searchLabel = subTab === 'by-cluster' ? 'Search Clusters' : 'Search Users';

  return (
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
              <Label htmlFor="ap-start-date" className="text-sm font-medium">
                Start Date
              </Label>
              <Input
                id="ap-start-date"
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
              <Label htmlFor="ap-end-date" className="text-sm font-medium">
                End Date
              </Label>
              <Input
                id="ap-end-date"
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
        <Label className="text-sm font-semibold">{searchLabel}</Label>

        <div className="relative">
          <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder={searchPlaceholder}
            value={localFilter}
            onChange={(e) => handleFilterChange(e.target.value)}
            className="pl-10"
          />
        </div>

        <div className="text-xs text-muted-foreground space-y-1">
          <div>
            <strong>Date Range:</strong> {formatDisplayDate(dateRange.start_date)} to{' '}
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
  );
};
