// AllPurposeDashboard — top-level container for the All-Purpose Clusters
// tab. Hosts the two sub-tabs (By Cluster / By User), shared filter card,
// and the per-tab table. Parallels `JobClustersDashboard.tsx` so the two
// tabs feel symmetrical.
//
// Sub-tab URL state is read from `?subtab=...` so a deep link or refresh
// lands on the right sub-tab; the parent `Dashboard.tsx` owns the
// top-level `?tab=...` param.
//
// See plan §4.1 / CP10 (`docs/plan_all_purpose_clusters_tab.md`).

import { useEffect, useState } from 'react';
import { format, subDays } from 'date-fns';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { AllPurposeSummaryCards } from './AllPurposeSummaryCards';
import { AllPurposeClusterFilterControls } from './AllPurposeClusterFilterControls';
import { AllPurposeClustersTable } from './AllPurposeClustersTable';
import { AllPurposeUsersTable } from './AllPurposeUsersTable';
import type { DateRange } from '@/types/job-spend';

const VALID_SUBTABS = ['by-cluster', 'by-user'] as const;
type SubTab = (typeof VALID_SUBTABS)[number];
const DEFAULT_SUBTAB: SubTab = 'by-cluster';

const readSubTabFromUrl = (): SubTab => {
  if (typeof window === 'undefined') return DEFAULT_SUBTAB;
  const params = new URLSearchParams(window.location.search);
  const candidate = params.get('subtab');
  return (VALID_SUBTABS as readonly string[]).includes(candidate ?? '')
    ? (candidate as SubTab)
    : DEFAULT_SUBTAB;
};

const writeSubTabToUrl = (next: SubTab) => {
  if (typeof window === 'undefined') return;
  const params = new URLSearchParams(window.location.search);
  if (next === DEFAULT_SUBTAB) {
    params.delete('subtab');
  } else {
    params.set('subtab', next);
  }
  const query = params.toString();
  const url = `${window.location.pathname}${query ? `?${query}` : ''}${window.location.hash}`;
  window.history.replaceState(null, '', url);
};

const AllPurposeDashboard = () => {
  // Match the job-cluster default window (last 30 days).
  const defaultDateRange: DateRange = {
    start_date: format(subDays(new Date(), 30), 'yyyy-MM-dd'),
    end_date: format(new Date(), 'yyyy-MM-dd'),
  };

  const [dateRange, setDateRange] = useState<DateRange>(defaultDateRange);
  // The two sub-tabs search different fields server-side, so each gets its
  // own state slot — switching sub-tabs preserves the right search box.
  const [clusterSearch, setClusterSearch] = useState<string>('');
  const [userSearch, setUserSearch] = useState<string>('');
  // Lazy-initialize from the URL so a deep link / refresh lands on the right
  // sub-tab without first flashing the default (plan §5.3).
  const [subTab, setSubTab] = useState<SubTab>(readSubTabFromUrl);

  // Keep the sub-tab in sync with browser back/forward (plan §5.3) — the
  // URL is the source of truth, so re-read it whenever history changes.
  useEffect(() => {
    const onPopState = () => setSubTab(readSubTabFromUrl());
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, []);

  const handleSubTabChange = (value: string) => {
    if (!(VALID_SUBTABS as readonly string[]).includes(value)) return;
    const next = value as SubTab;
    setSubTab(next);
    writeSubTabToUrl(next);
  };

  const activeSearch = subTab === 'by-cluster' ? clusterSearch : userSearch;
  const setActiveSearch =
    subTab === 'by-cluster' ? setClusterSearch : setUserSearch;

  return (
    <div className="space-y-6">
      <AllPurposeSummaryCards dateRange={dateRange} />

      <Card>
        <CardHeader>
          <CardTitle>Filters & Controls</CardTitle>
        </CardHeader>
        <CardContent>
          <AllPurposeClusterFilterControls
            // Remount the filter controls on a sub-tab switch so any pending
            // search debounce is cancelled (unmount cleanup) and the local
            // input picks up the new tab's committed search — otherwise a late
            // keystroke could write into the switched-to tab (plan §5.1).
            key={subTab}
            dateRange={dateRange}
            onDateRangeChange={setDateRange}
            searchTerm={activeSearch}
            onSearchTermChange={setActiveSearch}
            subTab={subTab}
          />
        </CardContent>
      </Card>

      {/* Single <Tabs> root spanning the header (TabsList) and the body
          (TabsContent) so Radix can wire aria-controls / aria-labelledby and
          arrow-key navigation across both (plan §5.2). */}
      <Card>
        <Tabs value={subTab} onValueChange={handleSubTabChange}>
          <CardHeader>
            <div className="flex items-start justify-between gap-4">
              <div>
                <CardTitle>All-Purpose Cluster Spending</CardTitle>
                <p className="text-sm text-muted-foreground mt-1">
                  {subTab === 'by-cluster'
                    ? 'One row per cluster. Click the arrow to expand and see daily cost. Click a cluster name to see config + AI analysis.'
                    : 'One row per cluster owner (user). Click the arrow to expand and see the clusters they own; click a cluster name to see config + AI analysis.'}
                </p>
              </div>
              <TabsList>
                <TabsTrigger value="by-cluster">By Cluster</TabsTrigger>
                <TabsTrigger value="by-user">By User</TabsTrigger>
              </TabsList>
            </div>
          </CardHeader>
          <CardContent>
            {/* Render only the active sub-tab's table to avoid double-firing
                the React Query hooks for both views every time the parent
                re-renders. */}
            {/* Remount each table on a filter change (date range / committed
                search) so pagination + expansion reset cleanly in one render
                pass (plan §3.2 / §3.3). */}
            <TabsContent value="by-cluster" className="mt-0">
              <AllPurposeClustersTable
                key={`${dateRange.start_date}|${dateRange.end_date}|${clusterSearch}`}
                dateRange={dateRange}
                searchTerm={clusterSearch}
              />
            </TabsContent>
            <TabsContent value="by-user" className="mt-0">
              <AllPurposeUsersTable
                key={`${dateRange.start_date}|${dateRange.end_date}|${userSearch}`}
                dateRange={dateRange}
                searchTerm={userSearch}
              />
            </TabsContent>
          </CardContent>
        </Tabs>
      </Card>
    </div>
  );
};

export default AllPurposeDashboard;
