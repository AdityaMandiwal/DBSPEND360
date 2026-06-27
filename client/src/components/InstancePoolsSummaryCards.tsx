// KPI strip + top-5 pools highlight for the Instance Pools tab.
//
// Parallels `AllPurposeSummaryCards.tsx`, but tuned to the pool data
// model (plan §4.1, CP10):
//
//   - Total Spend (DBU + EC2/EBS) and a dedicated cloud KPI. CP8
//     (plan_pool_pipeline_ec2_cost.md §4.4) joins pool VM cost in from
//     `dbspend360_pool_cloud_cost_explorer`, so `total_cloud_cost` now
//     carries the real summed EC2/EBS — `null` only when no pool-day in the
//     window has a cloud row yet, surfaced as "—" + note (plan §5), never a
//     misleading $0.
//   - Distinct pool count + distinct cluster count are both first-class
//     KPIs (plan §4.1) — the "cluster count" half is the closest lens on
//     "how many workloads are this pool serving" that v1 has, given
//     pools are inherently multi-tenant (plan §3.4).
//   - Orphan pool KPI (`pool_snapshot_missing = TRUE`) surfaces lost
//     metadata churn (cross-region or pre-Oct-2023 deleted-pool
//     retention; plan §3.5 / §10). Surfaced as its own card so
//     operators can spot the §3.5 three-state UX in aggregate.
//
// See plan §4.1 / CP10 (`docs/plan_instance_pools_tab.md`).

import {
  Activity,
  AlertTriangle,
  Cloud,
  DollarSign,
  Layers,
  Server,
} from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { ErrorState } from '@/components/ui/error-state';
import {
  useInstancePoolSummary,
  useTopInstancePools,
} from '@/hooks/useInstancePools';
import type { DateRange } from '@/types/job-spend';
import { useCloudPlatform } from '@/contexts/CloudPlatformContext';
import { useIsAws, AWS_CLOUD_LABEL } from '@/hooks/useCloudGate';

interface InstancePoolsSummaryCardsProps {
  dateRange: DateRange;
}

// `Intl.NumberFormat` is hoisted out of the component so it isn't
// reconstructed on every render (matches the pattern in
// `AllPurposeSummaryCards` / `SummaryCards`).
const currencyFormatter = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
const integerFormatter = new Intl.NumberFormat('en-US');
const formatCurrency = (amount: number) => currencyFormatter.format(amount);
const formatNumber = (n: number) => integerFormatter.format(n);
const formatPercent = (part: number, whole: number) =>
  whole > 0 ? `${Math.round((part / whole) * 100)}%` : '0%';

export const InstancePoolsSummaryCards = ({
  dateRange,
}: InstancePoolsSummaryCardsProps) => {
  const { config: cloudConfig } = useCloudPlatform();
  const isAws = useIsAws();
  const cloudLabel = isAws
    ? AWS_CLOUD_LABEL
    : `${cloudConfig?.compute_service || 'Cloud'} Cost`;
  const {
    data: metrics,
    isLoading: isMetricsLoading,
    isError: isMetricsError,
    refetch: refetchMetrics,
  } = useInstancePoolSummary(dateRange);
  const {
    data: topPools,
    isLoading: isTopPoolsLoading,
    isError: isTopPoolsError,
    refetch: refetchTopPools,
  } = useTopInstancePools(dateRange, 5);

  // Metrics-derived values are computed null-safely so the metrics-dependent
  // sections (KPI strip + pool-metadata card) render skeletons/errors
  // independently from the top-5 pools list below (poly3 — no whole-strip block).
  const dailyAverageSpend = metrics
    ? metrics.total_spend / Math.max(metrics.date_range_days, 1)
    : 0;
  const hasOrphanedPools = !!metrics && metrics.orphaned_pools > 0;

  // CP8: pool EC2/EBS cloud cost is now joined into the rollup (plan §4.4),
  // so the headline is total spend (DBU + cloud), not DBU alone.
  // `total_cloud_cost` is NULL only when no pool-day in the window carries a
  // cloud row yet — surfaced as "—" + note, never a misleading $0 (plan §5).
  const cloudCost = metrics?.total_cloud_cost;
  const cloudPctOfTotal =
    metrics && cloudCost != null && metrics.total_spend > 0
      ? formatPercent(cloudCost, metrics.total_spend)
      : null;

  return (
    <div className="space-y-6">
      {/* KPI cards: Total Spend / EC2-EBS cloud / Active Pools / Active Clusters */}
      {isMetricsLoading ? (
        <KpiStripSkeleton />
      ) : isMetricsError ? (
        <ErrorState
          message="Couldn't load instance pool summary metrics. Please try again."
          onRetry={() => refetchMetrics()}
        />
      ) : !metrics ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
          <Card>
            <CardContent className="p-6">
              <div className="text-center text-muted-foreground">
                No instance pool data available for the selected date range
              </div>
            </CardContent>
          </Card>
        </div>
      ) : (
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
              {metrics.date_range_days !== 1 ? 's' : ''} period ·{' '}
              {formatCurrency(dailyAverageSpend)}/day avg
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">{cloudLabel}</CardTitle>
            <Cloud className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            {cloudCost != null ? (
              <>
                <div className="text-2xl font-bold text-sky-600">
                  {formatCurrency(cloudCost)}
                </div>
                <p className="text-xs text-muted-foreground mt-1">
                  {cloudPctOfTotal} of total · pool VM cost (DBU is{' '}
                  {formatCurrency(metrics.total_databricks_cost)})
                </p>
              </>
            ) : (
              <>
                <div
                  className="text-2xl font-bold text-muted-foreground cursor-help"
                  title="No pool-tag cloud row landed in this window — confirm the DatabricksInstancePoolId tag is enabled and Cost Explorer has caught up (plan §5)."
                >
                  —
                </div>
                <p className="text-xs text-muted-foreground mt-1">
                  no pool VM cost available yet
                </p>
              </>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Active Pools</CardTitle>
            <Layers className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-purple-600">
              {formatNumber(metrics.total_pools)}
            </div>
            <p className="text-xs text-muted-foreground mt-1">
              {formatCurrency(metrics.avg_cost_per_pool_day)}/pool-day avg · max{' '}
              {formatCurrency(metrics.max_cost_per_pool_day)}
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
              distinct clusters attached
            </p>
          </CardContent>
        </Card>
      </div>
      )}

      {/* Bottom strip: orphan pools card (left) + top-5 pools card (right) */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Orphan / metadata-state card — surfaces §3.5 three-state UX
            at the aggregate level. */}
        <Card>
          <CardHeader>
            <CardTitle className="text-lg flex items-center gap-2">
              <AlertTriangle
                className={`h-5 w-5 ${
                  hasOrphanedPools
                    ? 'text-amber-500'
                    : 'text-muted-foreground'
                }`}
              />
              Pool Metadata
            </CardTitle>
          </CardHeader>
          <CardContent>
            {isMetricsLoading ? (
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <Skeleton className="h-4 w-[120px]" />
                  <Skeleton className="h-8 w-[60px]" />
                </div>
                <Skeleton className="h-12 w-full mt-3" />
              </div>
            ) : isMetricsError ? (
              <ErrorState
                compact
                message="Couldn't load pool metadata."
                onRetry={() => refetchMetrics()}
              />
            ) : !metrics ? (
              <div className="text-center text-muted-foreground py-4 text-sm">
                No data available
              </div>
            ) : (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <div className="text-sm text-muted-foreground">
                  Orphaned pools
                </div>
                <div className="text-right">
                  <div
                    className={`text-2xl font-bold ${
                      hasOrphanedPools
                        ? 'text-amber-600'
                        : 'text-muted-foreground'
                    }`}
                    title="Pools with billing rows but no row in system.compute.instance_pools — typically deleted before retention or located in another region"
                  >
                    {formatNumber(metrics.orphaned_pools)}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    of {formatNumber(metrics.total_pools)} pool
                    {metrics.total_pools === 1 ? '' : 's'}
                  </div>
                </div>
              </div>
              <div className="text-xs text-muted-foreground border-t pt-3">
                {hasOrphanedPools ? (
                  <>
                    Cost data is still accurate for orphaned pools — only the
                    pool config is missing. Most common cause: deleted before
                    Oct 2023, or pool snapshot lives in another region.
                  </>
                ) : (
                  <>
                    All pools have current metadata in
                    {' '}<span className="font-mono">system.compute.instance_pools</span>.
                  </>
                )}
              </div>
            </div>
            )}
          </CardContent>
        </Card>

        {/* Top 5 Costliest Pools */}
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle className="text-lg">Top 5 Costliest Pools</CardTitle>
          </CardHeader>
          <CardContent>
            {isTopPoolsLoading ? (
              <TopListSkeleton />
            ) : isTopPoolsError ? (
              <ErrorState
                compact
                message="Couldn't load top pools."
                onRetry={() => refetchTopPools()}
              />
            ) : topPools && topPools.length > 0 ? (
              <div className="space-y-3">
                {topPools.map((pool, index) => {
                  const hasName =
                    !!pool.pool_name && pool.pool_name.trim().length > 0;
                  const label = hasName
                    ? pool.pool_name!
                    : `Pool ${pool.instance_pool_id}`;
                  return (
                    <div
                      key={pool.instance_pool_id}
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
                          title={
                            hasName
                              ? `${label} — ${pool.instance_pool_id}`
                              : `Unnamed — ${pool.instance_pool_id}`
                          }
                        >
                          {label}
                        </span>
                      </div>
                      <div className="text-right shrink-0 ml-2">
                        <div className="text-sm font-semibold">
                          {formatCurrency(pool.total_cost)}
                        </div>
                        <div className="text-xs text-muted-foreground">
                          {pool.cluster_count} cluster
                          {pool.cluster_count === 1 ? '' : 's'} ·{' '}
                          {pool.active_days} day
                          {pool.active_days === 1 ? '' : 's'}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <EmptyTopList label="No pools found for this period" />
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
};

const TopListSkeleton = () => (
  <div className="space-y-3">
    {[...Array(5)].map((_, i) => (
      <div key={i} className="flex justify-between items-center">
        <Skeleton className="h-4 w-[160px]" />
        <Skeleton className="h-4 w-[100px]" />
      </div>
    ))}
  </div>
);

const KpiStripSkeleton = () => (
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

const EmptyTopList = ({ label }: { label: string }) => (
  <div className="text-center text-muted-foreground py-4 flex items-center justify-center gap-2">
    <Activity className="h-4 w-4" />
    <span className="text-sm">{label}</span>
  </div>
);
