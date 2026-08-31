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
//   - Daily Pool Spend Trend sparkline (avg/day + peak day) replaces the
//     old orphan-metadata tile so operators see spend shape at a glance.
//
// See plan §4.1 / CP10 (`docs/plan_instance_pools_tab.md`).

import {
  Activity,
  AlertTriangle,
  Cloud,
  DollarSign,
  Info,
  Layers,
  Server,
  TrendingUp,
} from 'lucide-react';
import { format, parseISO } from 'date-fns';
import { Area, AreaChart, ResponsiveContainer, Tooltip, YAxis } from 'recharts';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { ErrorState } from '@/components/ui/error-state';
import {
  useInstancePoolDailyTrend,
  useInstancePoolSummary,
  useTopInstancePools,
} from '@/hooks/useInstancePools';
import type { DateRange } from '@/types/job-spend';
import type { InstancePoolDailyTrendPoint } from '@/types/instance-pool';
import { useCloudPlatform } from '@/contexts/CloudPlatformContext';
import { CostCoverageMix } from './CostCoverageMix';
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
const formatTrendDate = (isoDate: string) => {
  try {
    return format(parseISO(isoDate), 'MMM d');
  } catch {
    return isoDate;
  }
};

const summarizeTrend = (points: InstancePoolDailyTrendPoint[]) => {
  if (points.length === 0) {
    return { avgPerDay: 0, peak: null as InstancePoolDailyTrendPoint | null };
  }
  const total = points.reduce((sum, p) => sum + p.total_cost, 0);
  const peak = points.reduce((best, p) =>
    p.total_cost > best.total_cost ? p : best,
  );
  return {
    avgPerDay: total / points.length,
    peak: peak.total_cost > 0 ? peak : null,
  };
};

export const InstancePoolsSummaryCards = ({
  dateRange,
}: InstancePoolsSummaryCardsProps) => {
  const { config: cloudConfig } = useCloudPlatform();
  const isAws = useIsAws();
  const isGcp = cloudConfig?.platform === 'GCP';
  const cloudLabel = isGcp
    ? 'Idle/Warm Pool Cloud Cost'
    : isAws
      ? `Idle/Warm ${AWS_CLOUD_LABEL}`
      : `Idle/Warm ${cloudConfig?.compute_service || 'Cloud'} Cost`;
  const {
    data: metrics,
    isLoading: isMetricsLoading,
    isError: isMetricsError,
    refetch: refetchMetrics,
  } = useInstancePoolSummary(dateRange);
  const {
    data: trendPoints,
    isLoading: isTrendLoading,
    isError: isTrendError,
    refetch: refetchTrend,
  } = useInstancePoolDailyTrend(dateRange);
  const {
    data: topPools,
    isLoading: isTopPoolsLoading,
    isError: isTopPoolsError,
    refetch: refetchTopPools,
  } = useTopInstancePools(dateRange, 5);

  // Metrics-derived values are computed null-safely so the metrics-dependent
  // sections (KPI strip + trend card) render skeletons/errors
  // independently from the top-5 pools list below (poly3 — no whole-strip block).
  const dailyAverageSpend = metrics
    ? metrics.total_spend / Math.max(metrics.date_range_days, 1)
    : 0;

  const trendSummary = trendPoints ? summarizeTrend(trendPoints) : null;
  const hasTrendSpend =
    !!trendPoints && trendPoints.some((p) => p.total_cost > 0);
  const cloudDataIsPartial =
    !!metrics &&
    metrics.total_pools > 0 &&
    (!metrics.latest_cloud_date ||
      metrics.latest_cloud_date < dateRange.end_date);
  const overallDataIsPartial =
    !!metrics?.latest_data_date &&
    metrics.latest_data_date < dateRange.end_date;

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
                {(metrics.dbu_in_non_covered_workspaces ?? 0) > 0 && (
                  <>
                    {' '}
                    ·{' '}
                    {formatCurrency(
                      metrics.dbu_in_non_covered_workspaces ?? 0,
                    )}{' '}
                    DBU in non-covered workspaces
                  </>
                )}
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Cost Mix</CardTitle>
              <Cloud className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <CostCoverageMix
                compact
                totalSpend={metrics.total_spend}
                coveredCloudCost={metrics.covered_cloud_cost}
                coveredDatabricksCost={metrics.covered_databricks_cost}
                uncoveredCloudCost={metrics.uncovered_cloud_cost}
                uncoveredDatabricksCost={
                  metrics.dbu_in_non_covered_workspaces ?? 0
                }
                cloudLabel={cloudLabel}
                formatCurrency={formatCurrency}
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">
                Active Pools
              </CardTitle>
              <Layers className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold text-purple-600">
                {formatNumber(metrics.total_pools)}
              </div>
              <p className="text-xs text-muted-foreground mt-1">
                {formatCurrency(metrics.avg_cost_per_pool_day)}/pool-day avg ·
                max {formatCurrency(metrics.max_cost_per_pool_day)}
                {metrics.orphaned_pools > 0 && (
                  <>
                    {' '}
                    · {formatNumber(metrics.orphaned_pools)} metadata
                    unavailable
                  </>
                )}
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

      {!isMetricsLoading &&
        !isMetricsError &&
        metrics &&
        (cloudDataIsPartial || overallDataIsPartial) && (
          <div className="flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-500/40 dark:bg-amber-500/10 dark:text-amber-200">
            <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
            <div>
              <div className="font-semibold">
                Selected-window data is incomplete.
              </div>
              <div className="text-xs mt-1 opacity-90">
                {metrics.latest_cloud_date
                  ? `Idle/warm cloud cost is available through ${formatTrendDate(metrics.latest_cloud_date)} (${metrics.cloud_data_days} of ${metrics.date_range_days} calendar days contain cloud data).`
                  : 'No idle/warm pool cloud cost has landed in this window.'}{' '}
                {metrics.latest_data_date &&
                  metrics.latest_data_date < dateRange.end_date &&
                  `The newest pool spend row is ${formatTrendDate(metrics.latest_data_date)}.`}{' '}
                Totals cover landed rows only and should not be treated as
                complete for the full date range.
              </div>
            </div>
          </div>
        )}

      {/* DBU overlap disclosure (issue #4): pool DBU is an alternate lens on
          usage keyed by instance_pool_id, with NO cluster_source filter — a
          pool-backed job/all-purpose cluster's DBU appears here AND on its
          native tab. Cloud cost is netted disjoint across tabs, but DBU is
          not, so tab totals must not be summed into a grand total. */}
      {!isMetricsLoading && !isMetricsError && metrics && (
        <p className="flex items-start gap-1.5 text-xs text-muted-foreground">
          <Info className="h-3.5 w-3.5 mt-0.5 shrink-0" />
          <span>
            Pool DBU is an alternate lens on the same usage — a pool-backed job
            or all-purpose cluster is also counted on its own tab. Cloud cost is
            de-duplicated across tabs, but DBU is not, so don't add this tab's
            total to the other tabs.
          </span>
        </p>
      )}

      {/* Bottom strip: daily trend card (left) + top-5 pools card (right) */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Card>
          <CardHeader>
            <CardTitle className="text-lg flex items-center gap-2">
              <TrendingUp className="h-5 w-5 text-muted-foreground" />
              Daily Pool Spend Trend
            </CardTitle>
          </CardHeader>
          <CardContent>
            {isTrendLoading ? (
              <div className="space-y-3">
                <Skeleton className="h-[72px] w-full" />
                <div className="flex justify-between">
                  <Skeleton className="h-8 w-[90px]" />
                  <Skeleton className="h-8 w-[110px]" />
                </div>
              </div>
            ) : isTrendError ? (
              <ErrorState
                compact
                message="Couldn't load daily pool spend trend."
                onRetry={() => refetchTrend()}
              />
            ) : !trendPoints || trendPoints.length === 0 ? (
              <div className="text-center text-muted-foreground py-4 text-sm">
                No data available
              </div>
            ) : (
              <div className="space-y-3">
                <div className="h-[72px] w-full">
                  {hasTrendSpend ? (
                    <ResponsiveContainer width="100%" height="100%">
                      <AreaChart
                        data={trendPoints}
                        margin={{ top: 4, right: 0, left: 0, bottom: 0 }}
                      >
                        <defs>
                          <linearGradient
                            id="poolTrendFill"
                            x1="0"
                            y1="0"
                            x2="0"
                            y2="1"
                          >
                            <stop
                              offset="0%"
                              stopColor="#2563eb"
                              stopOpacity={0.35}
                            />
                            <stop
                              offset="100%"
                              stopColor="#2563eb"
                              stopOpacity={0.02}
                            />
                          </linearGradient>
                        </defs>
                        <YAxis hide domain={[0, 'auto']} />
                        <Tooltip
                          cursor={{ stroke: '#94a3b8', strokeWidth: 1 }}
                          content={({ active, payload }) => {
                            if (!active || !payload?.length) return null;
                            const point = payload[0]
                              .payload as InstancePoolDailyTrendPoint;
                            return (
                              <div className="rounded-md border bg-background px-2.5 py-1.5 text-xs shadow-sm">
                                <div className="font-medium">
                                  {formatTrendDate(point.usage_date)}
                                </div>
                                <div className="text-muted-foreground">
                                  {formatCurrency(point.total_cost)}
                                </div>
                              </div>
                            );
                          }}
                        />
                        <Area
                          type="monotone"
                          dataKey="total_cost"
                          stroke="#2563eb"
                          strokeWidth={1.5}
                          fill="url(#poolTrendFill)"
                          isAnimationActive={false}
                        />
                      </AreaChart>
                    </ResponsiveContainer>
                  ) : (
                    <div className="h-full flex items-center justify-center text-sm text-muted-foreground">
                      No pool spend in this window
                    </div>
                  )}
                </div>
                <div className="flex items-start justify-between gap-3 border-t pt-3">
                  <div>
                    <div className="text-xs text-muted-foreground">
                      Avg / day
                    </div>
                    <div className="text-sm font-semibold">
                      {formatCurrency(trendSummary?.avgPerDay ?? 0)}
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-xs text-muted-foreground">
                      Peak day
                    </div>
                    {trendSummary?.peak ? (
                      <>
                        <div className="text-sm font-semibold">
                          {formatCurrency(trendSummary.peak.total_cost)}
                        </div>
                        <div className="text-xs text-muted-foreground">
                          {formatTrendDate(trendSummary.peak.usage_date)}
                        </div>
                      </>
                    ) : (
                      <div className="text-sm font-semibold text-muted-foreground">
                        —
                      </div>
                    )}
                  </div>
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
                          {pool.active_days} cost day
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
