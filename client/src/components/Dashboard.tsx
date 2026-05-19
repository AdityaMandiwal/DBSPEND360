import { useState } from 'react';
import { format, subDays } from 'date-fns';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { SummaryCards } from './SummaryCards';
import { FilterControls } from './FilterControls';
import { GroupedJobTable } from './GroupedJobTable';
import { JobBreakdownModal } from './JobBreakdownModal';
import { ThemeToggle } from './ThemeToggle';
import { DateRange, JobRun } from '@/types/job-spend';

const Dashboard = () => {
  // Default to last 30 days as specified in requirements
  const defaultDateRange: DateRange = {
    start_date: format(subDays(new Date(), 30), 'yyyy-MM-dd'),
    end_date: format(new Date(), 'yyyy-MM-dd'),
  };

  const [dateRange, setDateRange] = useState<DateRange>(defaultDateRange);
  const [jobFilter, setJobFilter] = useState<string>('');
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
    <div className="min-h-screen bg-background text-foreground">
      <div className="container mx-auto p-6 space-y-6">
        {/* Header */}
        <div className="flex items-start justify-between gap-4">
          <div className="flex flex-col space-y-2">
            <h1 className="text-3xl font-bold text-foreground">
              DBSpend360
            </h1>
            <p className="text-muted-foreground">
              Databricks Job Cost Analytics Dashboard
            </p>
          </div>
          <ThemeToggle />
        </div>

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
            <GroupedJobTable
              dateRange={dateRange}
              jobFilter={jobFilter}
              onRunClick={handleRunClick}
            />
          </CardContent>
        </Card>

        {/* Drill-down Modal */}
        {selectedJobId && selectedRun && (
          <JobBreakdownModal
            jobId={selectedJobId}
            runId={selectedRun.run_id}
            isOpen={isBreakdownModalOpen}
            onClose={handleModalClose}
          />
        )}
      </div>
    </div>
  );
};

export default Dashboard;