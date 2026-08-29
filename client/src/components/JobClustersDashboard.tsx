import { useState } from 'react';
import { format, subDays } from 'date-fns';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { SummaryCards } from './SummaryCards';
import { CoverageBanner } from './CoverageBanner';
import { FilterControls } from './FilterControls';
import { GroupedJobTable } from './GroupedJobTable';
import { JobBreakdownModal } from './JobBreakdownModal';
import { DateRange, JobRun } from '@/types/job-spend';

const JobClustersDashboard = () => {
  // Default to last 30 days as specified in requirements
  const defaultDateRange: DateRange = {
    start_date: format(subDays(new Date(), 29), 'yyyy-MM-dd'),
    end_date: format(new Date(), 'yyyy-MM-dd'),
  };

  const [dateRange, setDateRange] = useState<DateRange>(defaultDateRange);
  const [jobFilter, setJobFilter] = useState<string>('');
  const [isTableFetching, setIsTableFetching] = useState(false);
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [selectedRun, setSelectedRun] = useState<JobRun | null>(null);
  const [isBreakdownModalOpen, setIsBreakdownModalOpen] = useState(false);

  const handleRunClick = (jobId: string, run: JobRun) => {
    setSelectedJobId(jobId);
    setSelectedRun(run);
    setIsBreakdownModalOpen(true);
  };

  const handleModalClose = () => {
    setIsBreakdownModalOpen(false);
    setSelectedJobId(null);
    setSelectedRun(null);
  };

  return (
    <div className="space-y-6">
      <CoverageBanner tab="job" dateRange={dateRange} />

      {/* Summary Cards */}
      <SummaryCards dateRange={dateRange} />

      {/* Filter Controls */}
      <Card>
        <CardHeader>
          <CardTitle>Filters & Controls</CardTitle>
        </CardHeader>
        <CardContent>
          <FilterControls
            dateRange={dateRange}
            onDateRangeChange={setDateRange}
            jobFilter={jobFilter}
            onJobFilterChange={setJobFilter}
            isSearching={isTableFetching}
          />
        </CardContent>
      </Card>

      {/* Job Spend Table */}
      <Card>
        <CardHeader>
          <CardTitle>Job Spending Details</CardTitle>
          <p className="text-sm text-muted-foreground">
            Jobs are grouped by Job ID. Click the arrow to expand and see individual runs.
            Click on a run to see detailed cost breakdown.
          </p>
        </CardHeader>
        <CardContent>
          {/* Remount the table on any filter change (date range / committed
              search) so pagination resets to page 1 and the expansion set
              clears in the same render pass — no flash of the old page slice
              and no stale expanded rows (plan §3.2 / §3.3). */}
          <GroupedJobTable
            key={`${dateRange.start_date}|${dateRange.end_date}|${jobFilter}`}
            dateRange={dateRange}
            jobFilter={jobFilter}
            onRunClick={handleRunClick}
            onFetchingChange={setIsTableFetching}
          />
        </CardContent>
      </Card>

      {/* Drill-down Modal */}
      {selectedJobId && selectedRun && (
        <JobBreakdownModal
          jobId={selectedJobId}
          runId={selectedRun.run_id}
          dateRange={dateRange}
          isOpen={isBreakdownModalOpen}
          onClose={handleModalClose}
        />
      )}
    </div>
  );
};

export default JobClustersDashboard;
