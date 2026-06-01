import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { SummaryCards } from "./SummaryCards";
import { FilterControls } from "./FilterControls";
import { GroupedJobTable } from "./GroupedJobTable";
import { JobBreakdownModal } from "./JobBreakdownModal";
import { JobRun } from "@/types/job-spend";
import { useDashboard } from "./DashboardContext";

export const JobsTab = () => {
  const { dateRange, setDateRange } = useDashboard();

  const [jobFilter, setJobFilter] = useState<string>("");
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
      <SummaryCards dateRange={dateRange} />

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

      <Card>
        <CardHeader>
          <CardTitle>Job Spending Details</CardTitle>
          <p className="text-sm text-muted-foreground">
            Jobs are grouped by Job ID. Click the arrow to expand and see
            individual runs. Click on a run to see detailed cost breakdown.
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

      {selectedJobId && selectedRun && (
        <JobBreakdownModal
          jobId={selectedJobId}
          runId={selectedRun.run_id}
          isOpen={isBreakdownModalOpen}
          onClose={handleModalClose}
        />
      )}
    </div>
  );
};

export default JobsTab;
