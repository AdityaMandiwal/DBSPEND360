import { Search } from 'lucide-react';
import { format } from 'date-fns';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { DateRange } from '@/types/job-spend';
import { useDatePresets } from '@/hooks/useJobSpends';
import { cn } from '@/lib/utils';

interface FilterControlsProps {
  dateRange: DateRange;
  onDateRangeChange: (dateRange: DateRange) => void;
  jobFilter: string;
  onJobFilterChange: (filter: string) => void;
}

export const FilterControls = ({
  dateRange,
  onDateRangeChange,
  jobFilter,
  onJobFilterChange,
}: FilterControlsProps) => {
  const { data: presets } = useDatePresets();

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
                  "bg-blue-50 border-blue-200 text-blue-700"
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
                className="mt-1"
              />
            </div>
          </div>
        </div>
      </div>

      {/* Job Filter Controls */}
      <div className="space-y-4">
        <Label className="text-sm font-semibold">Search Jobs</Label>

        <div className="relative">
          <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search by job name or ID..."
            value={jobFilter}
            onChange={(e) => onJobFilterChange(e.target.value)}
            className="pl-10"
          />
        </div>

        {/* Filter Summary */}
        <div className="text-xs text-muted-foreground space-y-1">
          <div>
            <strong>Date Range:</strong> {formatDisplayDate(dateRange.start_date)} to {formatDisplayDate(dateRange.end_date)}
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