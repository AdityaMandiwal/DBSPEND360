import { useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { Badge } from '@/components/ui/badge';
import {
  DollarSign,
  Activity,
  BarChart3,
  AlertTriangle,
  Search,
} from 'lucide-react';
import { useSummaryMetrics, useTopJobs } from '@/hooks/useJobSpends';
import { DateRange } from '@/types/job-spend';
import { useCloudPlatform } from '@/contexts/CloudPlatformContext';
import {
  useIsAws,
  useIsSegmentedPlatform,
  AWS_CLOUD_LABEL,
} from '@/hooks/useCloudGate';
import { OtherCostBreakdownModal } from './OtherCostBreakdownModal';
import { ErrorState } from '@/components/ui/error-state';
import { CostCoverageMix } from './CostCoverageMix';

interface SummaryCardsProps {
  dateRange: DateRange;
}

export const SummaryCards = ({ dateRange }: SummaryCardsProps) => {
  const { config: cloudConfig } = useCloudPlatform();
  const isAws = useIsAws();
  const isSegmentedPlatform = useIsSegmentedPlatform();
  const {
    data: metrics,
    isLoading: isMetricsLoading,
    isError: isMetricsError,
    refetch: refetchMetrics,
  } = useSummaryMetrics(dateRange);
  const {
    data: topJobs,
    isLoading: isTopJobsLoading,
    isError: isTopJobsError,
    refetch: refetchTopJobs,
  } = useTopJobs(dateRange, 5);
  const [showOtherBreakdown, setShowOtherBreakdown] = useState(false);

  const formatCurrency = (amount: number) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(amount);
  };

  const formatNumber = (num: number) => {
    return new Intl.NumberFormat('en-US').format(num);
  };

  // Metrics-derived values are computed null-safely so the metrics-dependent
  // sections (KPI strip + cost breakdown) can render skeletons/errors
  // independently from the top-5 list below (poly3 — no whole-strip block).
  const dailyAverageSpend = metrics
    ? metrics.total_spend / Math.max(metrics.date_range_days, 1)
    : 0;
  const hasSegmented = metrics?.total_compute_cost != null;
  // Positive allowlist (D14): segmented compute/storage/network is shown only for
  // Azure/GCP. AWS, Unknown, and the config-loading window fall to the always-correct
  // cloud-vs-DBU 2-slice — never the data-shape branch.
  const showSegmented = hasSegmented && isSegmentedPlatform;
  const computePct =
    showSegmented && metrics && metrics.covered_cloud_cost > 0
      ? ((metrics.total_compute_cost ?? 0) / metrics.covered_cloud_cost) * 100
      : 0;
  const storagePct =
    showSegmented && metrics && metrics.covered_cloud_cost > 0
      ? ((metrics.total_storage_cost ?? 0) / metrics.covered_cloud_cost) * 100
      : 0;
  const networkPct =
    showSegmented && metrics && metrics.covered_cloud_cost > 0
      ? ((metrics.total_network_cost ?? 0) / metrics.covered_cloud_cost) * 100
      : 0;
  const otherPct =
    showSegmented && metrics && metrics.covered_cloud_cost > 0
      ? ((metrics.total_other_cost ?? 0) / metrics.covered_cloud_cost) * 100
      : 0;
  const coveragePct = metrics?.classification_coverage_pct;

  return (
    <div className="space-y-6">
      {/* Main Metrics Cards */}
      {isMetricsLoading ? (
        <KpiStripSkeleton />
      ) : isMetricsError ? (
        <ErrorState
          message="Couldn't load summary metrics. Please try again."
          onRetry={() => refetchMetrics()}
        />
      ) : !metrics ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
          <Card>
            <CardContent className="p-6">
              <div className="text-center text-muted-foreground">
                No data available for the selected date range
              </div>
            </CardContent>
          </Card>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
          {/* Total Spend */}
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
                {(metrics.dbu_in_non_covered_workspaces ?? 0) > 0 && (
                  <>
                    {' '}
                    · includes{' '}
                    {formatCurrency(
                      metrics.dbu_in_non_covered_workspaces ?? 0,
                    )}{' '}
                    DBU from non-covered workspaces
                  </>
                )}
              </p>
            </CardContent>
          </Card>

          {/* Total Jobs */}
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Total Jobs</CardTitle>
              <Activity className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold text-green-600">
                {formatNumber(metrics.total_jobs)}
              </div>
              <p className="text-xs text-muted-foreground mt-1">
                {formatCurrency(dailyAverageSpend)}/day avg
              </p>
            </CardContent>
          </Card>

          {/* Average Cost */}
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">
                Average Cost
              </CardTitle>
              <BarChart3 className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold text-purple-600">
                {formatCurrency(metrics.average_cost)}
              </div>
              <p className="text-xs text-muted-foreground mt-1">
                per job execution
              </p>
            </CardContent>
          </Card>

          {/* Max Cost */}
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">
                Highest Cost
              </CardTitle>
              <AlertTriangle className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold text-red-600">
                {formatCurrency(metrics.max_cost)}
              </div>
              <p className="text-xs text-muted-foreground mt-1">
                single job execution
              </p>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Cost Breakdown Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Cloud vs Databricks Breakdown */}
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Cost Breakdown</CardTitle>
          </CardHeader>
          <CardContent>
            {isMetricsLoading ? (
              <BreakdownSkeleton />
            ) : isMetricsError ? (
              <ErrorState
                compact
                message="Couldn't load cost breakdown."
                onRetry={() => refetchMetrics()}
              />
            ) : !metrics ? (
              <div className="text-center text-muted-foreground py-4 text-sm">
                No data available
              </div>
            ) : (
              <div className="space-y-4">
                {showSegmented && (
                  <div className="space-y-4 border-b pb-4">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center space-x-2">
                        <div className="w-3 h-3 bg-blue-500 rounded-full"></div>
                        <span className="text-sm font-medium">Compute</span>
                      </div>
                      <div className="text-right">
                        <div className="font-semibold">
                          {formatCurrency(metrics.total_compute_cost ?? 0)}
                        </div>
                        <div className="text-xs text-muted-foreground">
                          {computePct.toFixed(1)}% of covered cloud
                        </div>
                      </div>
                    </div>

                    <div className="flex items-center justify-between">
                      <div className="flex items-center space-x-2">
                        <div className="w-3 h-3 bg-green-500 rounded-full"></div>
                        <span className="text-sm font-medium">Storage</span>
                      </div>
                      <div className="text-right">
                        <div className="font-semibold">
                          {formatCurrency(metrics.total_storage_cost ?? 0)}
                        </div>
                        <div className="text-xs text-muted-foreground">
                          {storagePct.toFixed(1)}% of covered cloud
                        </div>
                      </div>
                    </div>

                    <div className="flex items-center justify-between">
                      <div className="flex items-center space-x-2">
                        <div className="w-3 h-3 bg-amber-500 rounded-full"></div>
                        <span className="text-sm font-medium">Network</span>
                      </div>
                      <div className="text-right">
                        <div className="font-semibold">
                          {formatCurrency(metrics.total_network_cost ?? 0)}
                        </div>
                        <div className="text-xs text-muted-foreground">
                          {networkPct.toFixed(1)}% of covered cloud
                        </div>
                      </div>
                    </div>

                    {(metrics.total_other_cost ?? 0) > 0 && (
                      <button
                        type="button"
                        className="flex items-center justify-between w-full text-left cursor-pointer hover:bg-muted/60 rounded px-1 -mx-1 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        onClick={() => setShowOtherBreakdown(true)}
                        title="Click to view breakdown of unclassified costs"
                        aria-label="View breakdown of unclassified costs"
                      >
                        <div className="flex items-center space-x-2">
                          <div className="w-3 h-3 bg-gray-400 rounded-full"></div>
                          <span className="text-sm font-medium">
                            Other (Unclassified)
                          </span>
                          <Search
                            className="h-3 w-3 text-muted-foreground"
                            aria-hidden="true"
                          />
                        </div>
                        <div className="text-right">
                          <div className="font-semibold">
                            {formatCurrency(metrics.total_other_cost ?? 0)}
                          </div>
                          <div className="text-xs text-muted-foreground">
                            {otherPct.toFixed(1)}% of covered cloud
                          </div>
                        </div>
                      </button>
                    )}

                    {coveragePct != null && (
                      <div className="space-y-2 border-t pt-2">
                        <div className="flex items-center justify-between">
                          <span className="text-xs font-medium text-muted-foreground">
                            Classification Coverage
                          </span>
                          <div className="flex items-center gap-2">
                            <Badge
                              variant={
                                metrics.coverage_status === 'ok'
                                  ? 'default'
                                  : metrics.coverage_status === 'warning'
                                    ? 'secondary'
                                    : 'destructive'
                              }
                              className={`text-xs ${
                                metrics.coverage_status === 'ok'
                                  ? 'bg-green-100 text-green-700 hover:bg-green-100 dark:bg-green-500/15 dark:text-green-300 dark:hover:bg-green-500/15'
                                  : metrics.coverage_status === 'warning'
                                    ? 'bg-amber-100 text-amber-700 hover:bg-amber-100 dark:bg-amber-500/15 dark:text-amber-300 dark:hover:bg-amber-500/15'
                                    : 'bg-red-100 text-red-700 hover:bg-red-100 dark:bg-red-500/15 dark:text-red-300 dark:hover:bg-red-500/15'
                              }`}
                            >
                              {coveragePct.toFixed(1)}%
                            </Badge>
                          </div>
                        </div>
                        {metrics.coverage_warning && (
                          <div
                            className={`text-xs p-2 rounded flex items-start gap-1.5 ${
                              metrics.coverage_status === 'critical'
                                ? 'bg-red-50 text-red-700 dark:bg-red-500/10 dark:text-red-300'
                                : 'bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300'
                            }`}
                          >
                            <AlertTriangle className="h-3 w-3 mt-0.5 flex-shrink-0" />
                            <span>{metrics.coverage_warning}</span>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}
                <CostCoverageMix
                  totalSpend={metrics.total_spend}
                  coveredCloudCost={metrics.covered_cloud_cost}
                  coveredDatabricksCost={metrics.covered_databricks_cost}
                  uncoveredCloudCost={metrics.uncovered_cloud_cost}
                  uncoveredDatabricksCost={
                    metrics.dbu_in_non_covered_workspaces ?? 0
                  }
                  cloudLabel={
                    isAws
                      ? AWS_CLOUD_LABEL
                      : cloudConfig?.compute_display_name || 'Cloud Costs'
                  }
                  formatCurrency={formatCurrency}
                />
              </div>
            )}
            {isAws && metrics && (
              <p className="text-xs text-muted-foreground mt-4 pt-3 border-t">
                AWS shared infrastructure (S3, NAT, networking) is not
                cluster-attributable and is excluded.
              </p>
            )}
          </CardContent>
        </Card>

        {/* Top 5 Costliest Jobs */}
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Top 5 Costliest Jobs</CardTitle>
          </CardHeader>
          <CardContent>
            {isTopJobsLoading ? (
              <div className="space-y-3">
                {[...Array(5)].map((_, i) => (
                  <div key={i} className="flex justify-between items-center">
                    <Skeleton className="h-4 w-[120px]" />
                    <Skeleton className="h-4 w-[80px]" />
                  </div>
                ))}
              </div>
            ) : isTopJobsError ? (
              <ErrorState
                compact
                message="Couldn't load top jobs."
                onRetry={() => refetchTopJobs()}
              />
            ) : topJobs && topJobs.length > 0 ? (
              <div className="space-y-3">
                {topJobs.map((job, index) => {
                  const hasName =
                    !!job.job_name && job.job_name.trim().length > 0;
                  const displayLabel = hasName
                    ? job.job_name!
                    : `Job ${job.job_id}`;
                  return (
                    <div
                      key={job.job_id}
                      className="flex justify-between items-center"
                    >
                      <div className="flex items-center space-x-2">
                        <span className="text-xs bg-muted text-muted-foreground px-2 py-1 rounded">
                          #{index + 1}
                        </span>
                        <span
                          className={`text-sm font-medium ${hasName ? '' : 'font-mono text-muted-foreground'}`}
                          title={
                            hasName
                              ? displayLabel
                              : `Unnamed job — id ${job.job_id}`
                          }
                        >
                          {displayLabel}
                        </span>
                      </div>
                      <div className="text-right">
                        <div className="text-sm font-semibold">
                          {formatCurrency(job.total_cost)}
                        </div>
                        <div className="text-xs text-muted-foreground">
                          {job.run_count} run{job.run_count === 1 ? '' : 's'}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="text-center text-muted-foreground py-4">
                No jobs found for this period
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Other Cost Breakdown Modal */}
      <OtherCostBreakdownModal
        dateRange={dateRange}
        isOpen={showOtherBreakdown}
        onClose={() => setShowOtherBreakdown(false)}
      />
    </div>
  );
};

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

const BreakdownSkeleton = () => (
  <div className="space-y-4">
    {[...Array(3)].map((_, i) => (
      <div key={i} className="flex items-center justify-between">
        <Skeleton className="h-4 w-[100px]" />
        <Skeleton className="h-4 w-[80px]" />
      </div>
    ))}
    <Skeleton className="h-2.5 w-full mt-3" />
  </div>
);
