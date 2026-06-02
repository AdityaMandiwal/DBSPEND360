// Filter controls for the Instance Pools tab.
//
// Parallels `AllPurposeClusterFilterControls.tsx`. Same date presets and
// debounce-on-search pattern. The search box hits the new `search` query
// parameter on `/api/instance-pools/grouped`, which matches against
// pool name (case-insensitive substring), instance_pool_id (exact), and
// cluster_id (exact, via a back-reference subquery — see plan §5.1
// search-clause notes).
//
// Per plan §4.1 / §3.4 there is intentionally **no creator search field**
// here: the rollup table doesn't carry creator info, the list endpoint
// doesn't enrich per request, so a creator predicate would either
// silently match nothing or require fanning out one REST call per row
// (which would defeat the table's caching story).

import { useEffect, useRef, useState } from 'react';
import { Search } from 'lucide-react';
import { format } from 'date-fns';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import type { DateRange } from '@/types/job-spend';
import { useDatePresets } from '@/hooks/useJobSpends';
import { cn } from '@/lib/utils';

interface InstancePoolFilterControlsProps {
  dateRange: DateRange;
  onDateRangeChange: (dateRange: DateRange) => void;
  searchTerm: string;
  onSearchTermChange: (filter: string) => void;
}

export const InstancePoolFilterControls = ({
  dateRange,
  onDateRangeChange,
  searchTerm,
  onSearchTermChange,
}: InstancePoolFilterControlsProps) => {
  const { data: presets } = useDatePresets();
  const [localFilter, setLocalFilter] = useState(searchTerm);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    setLocalFilter(searchTerm);
  }, [searchTerm]);

  // Debounce mirror of `AllPurposeClusterFilterControls` / `FilterControls`'s
  // 300ms — keeps all three tabs feeling identical and avoids one query
  // per keystroke.
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
              <Label htmlFor="ip-start-date" className="text-sm font-medium">
                Start Date
              </Label>
              <Input
                id="ip-start-date"
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
              <Label htmlFor="ip-end-date" className="text-sm font-medium">
                End Date
              </Label>
              <Input
                id="ip-end-date"
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
        <Label className="text-sm font-semibold">Search Pools</Label>

        <div className="relative">
          <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search by pool name, pool ID, or cluster ID..."
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
  );
};
