// PipelineDashboard — top-level container for the Pipeline Compute tab.
//
// Mirrors `InstancePoolsDashboard.tsx` (single view, no inner `<Tabs>` —
// plan §3.3 / §4.1), with one extra piece of lifted state: the
// `selectedWorkloads` chip selection. It lives here (not inside the filter
// controls) so the summary KPI strip and the By-Pipeline table stay in
// lock-step — toggling a workload chip narrows BOTH at once (plan §3.1).
//
// The global tab footnote discloses the honesty caveats per plan §3.2 /
// §3.7 / CP3: list price (≠ invoice), the classic EC2/EBS VM cost now shown
// alongside DBU, and the instance-pool overlap for classic pipelines.
//
// See plan §4.1 / CP10 (`docs/plan_dlt_tab.md`).

import { useState } from 'react';
import { format, subDays } from 'date-fns';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { PipelineSummaryCards } from './PipelineSummaryCards';
import { CoverageBanner } from './CoverageBanner';
import { PipelineFilterControls } from './PipelineFilterControls';
import { PipelinesTable } from './PipelinesTable';
import type { DateRange } from '@/types/job-spend';

const PipelineDashboard = () => {
  // Match the other three tabs' default window (last 30 days) so users
  // pivoting between tabs see consistent scope until they pick a preset.
  const defaultDateRange: DateRange = {
    start_date: format(subDays(new Date(), 29), 'yyyy-MM-dd'),
    end_date: format(new Date(), 'yyyy-MM-dd'),
  };

  const [dateRange, setDateRange] = useState<DateRange>(defaultDateRange);
  const [searchTerm, setSearchTerm] = useState<string>('');
  const [selectedWorkloads, setSelectedWorkloads] = useState<string[]>([]);

  // Changing the date range can change which workloads even exist in the
  // window, so a chip selected for the old range would otherwise keep
  // filtering invisibly (plan §7.2). Clear the chip selection whenever the
  // range changes so the table + KPI strip show unfiltered results for the
  // new window.
  const handleDateRangeChange = (next: DateRange) => {
    setDateRange(next);
    setSelectedWorkloads([]);
  };

  return (
    <div className="space-y-6">
      <CoverageBanner tab="pipeline" dateRange={dateRange} />
      <PipelineSummaryCards
        dateRange={dateRange}
        selectedWorkloads={selectedWorkloads}
      />

      <Card>
        <CardHeader>
          <CardTitle>Filters & Controls</CardTitle>
        </CardHeader>
        <CardContent>
          <PipelineFilterControls
            dateRange={dateRange}
            onDateRangeChange={handleDateRangeChange}
            searchTerm={searchTerm}
            onSearchTermChange={setSearchTerm}
            selectedWorkloads={selectedWorkloads}
            onSelectedWorkloadsChange={setSelectedWorkloads}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Pipeline Compute Spending</CardTitle>
          <p className="text-sm text-muted-foreground mt-1">
            One row per pipeline-backed workload (DLT, DBSQL materialized views,
            online tables, vector search, model serving, AI functions). Click
            the arrow to expand and see daily spend; click the pipeline name for
            config and AI analysis.
          </p>
          <p className="text-xs text-muted-foreground mt-2">
            Databricks DBU is list price — it excludes account-level discounts
            (list ≠ your invoice). Total Cost always includes known DBU,
            including DBU from workspaces outside cloud billing coverage, plus
            cloud infrastructure cost where available. Cloud cost can be
            unavailable or partial for non-covered workspaces. Serverless DBU
            already bundles infrastructure, so it has no separate VM line and
            shows "—". Classic pipelines on instance pools may also appear
            under the Instance Pools tab — the same compute is shown through
            different lenses, so the tabs are not meant to sum.
          </p>
        </CardHeader>
        <CardContent>
          <PipelinesTable
            dateRange={dateRange}
            searchTerm={searchTerm}
            selectedWorkloads={selectedWorkloads}
          />
        </CardContent>
      </Card>
    </div>
  );
};

export default PipelineDashboard;
