// InstancePoolsDashboard — top-level container for the Instance Pools tab.
//
// Distinct from `AllPurposeDashboard.tsx` in two ways (plan §3.3):
//
//   1. **No inner `<Tabs>` shell.** The pool tab has a single By-Pool
//      view with two-level row expansion (pool → per-day → per-cluster);
//      there are no v1 sub-tabs.
//   2. **No By-User chargeback.** Pools are inherently multi-tenant
//      (plan §3.4); the closest "who is driving cost" lens v1 has is
//      the per-cluster drill-down already present in the table.
//
// See plan §4.1 / CP10 (`docs/plan_instance_pools_tab.md`).

import { useState } from 'react';
import { format, subDays } from 'date-fns';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { InstancePoolsSummaryCards } from './InstancePoolsSummaryCards';
import { InstancePoolFilterControls } from './InstancePoolFilterControls';
import { InstancePoolsTable } from './InstancePoolsTable';
import type { DateRange } from '@/types/job-spend';

const InstancePoolsDashboard = () => {
  // Match the other two tabs' default window (last 30 days) so users
  // pivoting between tabs see consistent scope until they pick a preset.
  const defaultDateRange: DateRange = {
    start_date: format(subDays(new Date(), 30), 'yyyy-MM-dd'),
    end_date: format(new Date(), 'yyyy-MM-dd'),
  };

  const [dateRange, setDateRange] = useState<DateRange>(defaultDateRange);
  const [searchTerm, setSearchTerm] = useState<string>('');

  return (
    <div className="space-y-6">
      <InstancePoolsSummaryCards dateRange={dateRange} />

      <Card>
        <CardHeader>
          <CardTitle>Filters & Controls</CardTitle>
        </CardHeader>
        <CardContent>
          <InstancePoolFilterControls
            dateRange={dateRange}
            onDateRangeChange={setDateRange}
            searchTerm={searchTerm}
            onSearchTermChange={setSearchTerm}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Instance Pool Spending</CardTitle>
          <p className="text-sm text-muted-foreground mt-1">
            One row per pool. Click the arrow to expand and see daily spend;
            expand a day to see per-cluster spend. Click the pool name to see
            pool config and AI analysis.
          </p>
          <p className="text-xs text-muted-foreground mt-2">
            v1 surfaces DBU cost only — pool cloud VM cost (idle + active) is
            tracked separately in the cloud-cost explorers and is a v2
            follow-up. Pool spend may overlap with the Job Clusters and
            All-Purpose tabs — see README for the three-lens cost model.
          </p>
        </CardHeader>
        <CardContent>
          <InstancePoolsTable
            dateRange={dateRange}
            searchTerm={searchTerm}
          />
        </CardContent>
      </Card>
    </div>
  );
};

export default InstancePoolsDashboard;
