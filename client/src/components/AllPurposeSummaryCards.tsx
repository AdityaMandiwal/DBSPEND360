// KPI strip + cost breakdown + top-5 highlights for the All-Purpose tab.
//
// Parallels `SummaryCards.tsx` for the Job Clusters tab but reports
// cluster + user counts (not job counts) and surfaces both "Top 5
// Costliest Clusters" and "Top 5 Costliest Users" — the latter is the
// chargeback hook that the Job Clusters tab doesn't have.
//
// See plan §4.1 (`docs/plan_all_purpose_clusters_tab.md`) and CP10.

import {
  Activity,
  AlertTriangle,
  BarChart3,
  DollarSign,
  Server,
  Users,
} from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import {
  useAllPurposeSummary,
  useAllPurposeTopClusters,
  useAllPurposeTopUsers,
} from '@/hooks/useAllPurposeClusters';
import type { DateRange } from '@/types/job-spend';
import { useCloudPlatform } from '@/contexts/CloudPlatformContext';

interface AllPurposeSummaryCardsProps {
  dateRange: DateRange;
}

// `Intl.NumberFormat` is hoisted out of the component so it isn't
// reconstructed on every render (matches the pattern in `SummaryCards`).
const currencyFormatter = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
const integerFormatter = new Intl.NumberFormat('en-US');
const formatCurrency = (amount: number) => currencyFormatter.format(amount);
const formatNumber = (n: number) => integerFormatter.format(n);

export const AllPurposeSummaryCards = ({
  dateRange,
}: AllPurposeSummaryCardsProps) => {
  const { config: cloudConfig } = useCloudPlatform();
  const { data: metrics, isLoading: isMetricsLoading } =
    useAllPurposeSummary(dateRange);
  const { data: topClusters, isLoading: isTopClustersLoading } =
    useAllPurposeTopClusters(dateRange, 5);
  const { data: topUsers, isLoading: isTopUsersLoading } =
    useAllPurposeTopUsers(dateRange, 5);

  if (isMetricsLoading) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        {[...Array(4)].map((_, i) => (
          <Card key={i}>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <Skeleton className="h-4 w-[100px]" />
              <Skeleton className="h-4 w-4" />
            </CardHeader>
            <CardContent>
              <Skeleton className="h-8 w-[120px] mb-2" />
              <Skeleton className="h-3 w-[80px]" />
            </CardContent>
          </Card>
        ))}
      </div>
    );
  }

  if (!metrics) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <Card>
          <CardContent className="p-6">
            <div className="text-center text-muted-foreground">
              No all-purpose data available for the selected date range
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  const dailyAverageSpend =
    metrics.total_spend / Math.max(metrics.date_range_days, 1);
  const cloudPercentage =
    metrics.total_spend > 0
      ? (metrics.total_cloud_cost / metrics.total_spend) * 100
      : 0;
  const databricksPercentage =
    metrics.total_spend > 0
      ? (metrics.total_databricks_cost / metrics.total_spend) * 100
      : 0;

  const hasSegmented = metrics.total_compute_cost != null;
  const safe = (n: number | null | undefined) => n ?? 0;
  const computePct =
    hasSegmented && metrics.total_cloud_cost > 0
      ? (safe(metrics.total_compute_cost) / metrics.total_cloud_cost) * 100
      : 0;
  const storagePct =
    hasSegmented && metrics.total_cloud_cost > 0
      ? (safe(metrics.total_storage_cost) / metrics.total_cloud_cost) * 100
      : 0;
  const networkPct =
    hasSegmented && metrics.total_cloud_cost > 0
      ? (safe(metrics.total_network_cost) / metrics.total_cloud_cost) * 100
      : 0;
  const otherPct =
    hasSegmented && metrics.total_cloud_cost > 0
      ? (safe(metrics.total_other_cost) / metrics.total_cloud_cost) * 100
      : 0;

  return (
    <div className="space-y-6">
      {/* KPI cards: Total Spend / Total Clusters / Total Users / Avg per cluster-day */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Total Spend</CardTitle>
            <DollarSign className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-blue-600">
              {formatCurrency(metrics.total_spend)}
            </div>
            <p className="text-xs text-muted-foreground mt-1">
              {metrics.date_range_days} day
              {metrics.date_range_days !== 1 ? 's' : ''} period
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">
              Active Clusters
            </CardTitle>
            <Server className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-green-600">
              {formatNumber(metrics.total_clusters)}
            </div>
            <p className="text-xs text-muted-foreground mt-1">
              {formatCurrency(dailyAverageSpend)}/day avg
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Active Users</CardTitle>
            <Users className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-purple-600">
              {formatNumber(metrics.total_users)}
            </div>
            <p className="text-xs text-muted-foreground mt-1">
              cluster owners with billed usage
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">
              Avg per Cluster-Day
            </CardTitle>
            <BarChart3 className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-amber-600">
              {formatCurrency(metrics.avg_cost_per_cluster_day)}
            </div>
            <p className="text-xs text-muted-foreground mt-1">
              max {formatCurrency(metrics.max_cost_per_cluster_day)}
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Cost breakdown + top-5 highlight cards */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Cost Breakdown */}
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Cost Breakdown</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              {hasSegmented ? (
                <>
                  <BreakdownRow
                    color="bg-blue-500"
                    label="Compute"
                    value={safe(metrics.total_compute_cost)}
                    pct={computePct}
                    pctLabel="of cloud"
                  />
                  <BreakdownRow
                    color="bg-green-500"
                    label="Storage"
                    value={safe(metrics.total_storage_cost)}
                    pct={storagePct}
                    pctLabel="of cloud"
                  />
                  <BreakdownRow
                    color="bg-amber-500"
                    label="Network"
                    value={safe(metrics.total_network_cost)}
                    pct={networkPct}
                    pctLabel="of cloud"
                  />
                  {safe(metrics.total_other_cost) > 0 && (
                    <BreakdownRow
                      color="bg-gray-400"
                      label="Other (Unclassified)"
                      value={safe(metrics.total_other_cost)}
                      pct={otherPct}
                      pctLabel="of cloud"
                    />
                  )}
                  <div className="border-t pt-2">
                    <BreakdownRow
                      color="bg-red-500"
                      label="Databricks (DBU)"
                      value={metrics.total_databricks_cost}
                      pct={databricksPercentage}
                      pctLabel="of total"
                    />
                  </div>
                  {/* Segmented totals bar — cloud first, then DBU */}
                  <div className="w-full bg-muted rounded-full h-2.5 mt-3 flex overflow-hidden">
                    <div
                      className="bg-blue-500 h-2.5"
                      style={{
                        width: `${(computePct * cloudPercentage) / 100}%`,
                      }}
                    />
                    <div
                      className="bg-green-500 h-2.5"
                      style={{
                        width: `${(storagePct * cloudPercentage) / 100}%`,
                      }}
                    />
                    <div
                      className="bg-amber-500 h-2.5"
                      style={{
                        width: `${(networkPct * cloudPercentage) / 100}%`,
                      }}
                    />
                    {otherPct > 0 && (
                      <div
                        className="bg-gray-400 h-2.5"
                        style={{
                          width: `${(otherPct * cloudPercentage) / 100}%`,
                        }}
                      />
                    )}
                    <div
                      className="bg-red-500 h-2.5"
                      style={{ width: `${databricksPercentage}%` }}
                    />
                  </div>
                </>
              ) : (
                <>
                  <BreakdownRow
                    color="bg-blue-500"
                    label={cloudConfig?.compute_display_name || 'Cloud Costs'}
                    value={metrics.total_cloud_cost}
                    pct={cloudPercentage}
                  />
                  <BreakdownRow
                    color="bg-red-500"
                    label="Databricks Costs"
                    value={metrics.total_databricks_cost}
                    pct={databricksPercentage}
                  />
                  <div className="w-full bg-muted rounded-full h-2 mt-3 flex overflow-hidden">
                    <div
                      className="bg-blue-500 h-2"
                      style={{ width: `${cloudPercentage}%` }}
                    />
                    <div
                      className="bg-red-500 h-2"
                      style={{ width: `${databricksPercentage}%` }}
                    />
                  </div>
                </>
              )}
            </div>
          </CardContent>
        </Card>

        {/* Top 5 Costliest Clusters */}
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Top 5 Costliest Clusters</CardTitle>
          </CardHeader>
          <CardContent>
            {isTopClustersLoading ? (
              <TopListSkeleton />
            ) : topClusters && topClusters.length > 0 ? (
              <div className="space-y-3">
                {topClusters.map((cluster, index) => {
                  const hasName =
                    !!cluster.cluster_name &&
                    cluster.cluster_name.trim().length > 0;
                  const label = hasName
                    ? cluster.cluster_name!
                    : `Cluster ${cluster.cluster_id}`;
                  return (
                    <div
                      key={cluster.cluster_id}
                      className="flex justify-between items-center"
                    >
                      <div className="flex items-center space-x-2 min-w-0">
                        <span className="text-xs bg-muted text-muted-foreground px-2 py-1 rounded">
                          #{index + 1}
                        </span>
                        <span
                          className={`text-sm font-medium truncate ${
                            hasName ? '' : 'font-mono text-muted-foreground'
                          }`}
                          title={hasName ? label : `Unnamed — ${cluster.cluster_id}`}
                        >
                          {label}
                        </span>
                      </div>
                      <div className="text-right shrink-0 ml-2">
                        <div className="text-sm font-semibold">
                          {formatCurrency(cluster.total_cost)}
                        </div>
                        <div className="text-xs text-muted-foreground">
                          {cluster.active_days} day
                          {cluster.active_days === 1 ? '' : 's'}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <EmptyTopList label="No clusters found for this period" />
            )}
          </CardContent>
        </Card>

        {/* Top 5 Costliest Users (chargeback) */}
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Top 5 Costliest Users</CardTitle>
          </CardHeader>
          <CardContent>
            {isTopUsersLoading ? (
              <TopListSkeleton />
            ) : topUsers && topUsers.length > 0 ? (
              <div className="space-y-3">
                {topUsers.map((user, index) => {
                  const isUnknown = user.user_id === '__unknown__';
                  return (
                    <div
                      key={user.user_id}
                      className="flex justify-between items-center"
                    >
                      <div className="flex items-center space-x-2 min-w-0">
                        <span className="text-xs bg-muted text-muted-foreground px-2 py-1 rounded">
                          #{index + 1}
                        </span>
                        <span
                          className={`text-sm font-medium truncate ${
                            isUnknown ? 'italic text-muted-foreground' : ''
                          }`}
                          title={isUnknown ? 'Owner could not be resolved (cluster snapshot missing)' : user.user_id}
                        >
                          {isUnknown ? 'Unknown' : user.user_id}
                        </span>
                      </div>
                      <div className="text-right shrink-0 ml-2">
                        <div className="text-sm font-semibold">
                          {formatCurrency(user.total_cost)}
                        </div>
                        <div className="text-xs text-muted-foreground">
                          {user.cluster_count} cluster
                          {user.cluster_count === 1 ? '' : 's'}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <EmptyTopList label="No users found for this period" />
            )}
          </CardContent>
        </Card>
      </div>

      {/* Coverage banner only when min is suspiciously low */}
      {metrics.min_cost_per_cluster_day === 0 && metrics.total_clusters > 0 && (
        <Card>
          <CardContent className="p-3">
            <div className="flex items-start gap-2 text-xs text-muted-foreground">
              <AlertTriangle className="h-3.5 w-3.5 mt-0.5 text-amber-500 shrink-0" />
              <span>
                Some cluster-days have zero cost (DBU-only or cloud-only rows
                left after the merge). The reconciliation invariant is still
                enforced upstream — these typically reflect free-tier or
                trial-credit usage.
              </span>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
};

// Helper components kept private to this module — they only make sense in
// the breakdown / top-list shape and aren't worth their own files.

const BreakdownRow = ({
  color,
  label,
  value,
  pct,
  pctLabel,
}: {
  color: string;
  label: string;
  value: number;
  pct: number;
  pctLabel?: string;
}) => (
  <div className="flex items-center justify-between">
    <div className="flex items-center space-x-2">
      <div className={`w-3 h-3 ${color} rounded-full`} />
      <span className="text-sm font-medium">{label}</span>
    </div>
    <div className="text-right">
      <div className="font-semibold">{formatCurrency(value)}</div>
      <div className="text-xs text-muted-foreground">
        {pct.toFixed(1)}%{pctLabel ? ` ${pctLabel}` : ''}
      </div>
    </div>
  </div>
);

const TopListSkeleton = () => (
  <div className="space-y-3">
    {[...Array(5)].map((_, i) => (
      <div key={i} className="flex justify-between items-center">
        <Skeleton className="h-4 w-[120px]" />
        <Skeleton className="h-4 w-[80px]" />
      </div>
    ))}
  </div>
);

const EmptyTopList = ({ label }: { label: string }) => (
  <div className="text-center text-muted-foreground py-4 flex items-center justify-center gap-2">
    <Activity className="h-4 w-4" />
    <span className="text-sm">{label}</span>
  </div>
);
