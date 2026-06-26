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
import { PipelineFilterControls } from './PipelineFilterControls';
import { PipelinesTable } from './PipelinesTable';
import type { DateRange } from '@/types/job-spend';

const PipelineDashboard = () => {
  // Match the other three tabs' default window (last 30 days) so users
  // pivoting between tabs see consistent scope until they pick a preset.
  const defaultDateRange: DateRange = {
    start_date: format(subDays(new Date(), 30), 'yyyy-MM-dd'),
    end_date: format(new Date(), 'yyyy-MM-dd'),
  };

  const [dateRange, setDateRange] = useState<DateRange>(defaultDateRange);
  const [searchTerm, setSearchTerm] = useState<string>('');
  const [selectedWorkloads, setSelectedWorkloads] = useState<string[]>([]);

  return (
    <div className="space-y-6">
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
            onDateRangeChange={setDateRange}
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
            (list ≠ your invoice). Classic pipelines also show their EC2/EBS VM
            cost (from AWS Cost Explorer, keyed by ClusterId), included in Total
            Cost; serverless DBU already bundles infrastructure, so it has no
            separate VM line and shows "—". Classic pipelines on instance pools
            may also appear under the Instance Pools tab — see README for the
            cost model.
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
