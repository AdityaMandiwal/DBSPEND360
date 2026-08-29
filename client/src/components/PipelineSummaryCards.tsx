// KPI strip + workload breakdown + top-5 highlight for the Pipeline Compute
// tab.
//
// Parallels `InstancePoolsSummaryCards.tsx`, tuned to the pipeline data model
// (plan §4.1 / CP10):
//
//   - Total spend includes all known DBU plus available cloud cost. Freshness
//     fields disclose how much of the selected window has landed.
//   - Workload breakdown card — the per-`workload_type` `$` map (exact,
//     reconciles row-for-row with staging — plan §3.1). This is the headline
//     truth indicator: it shows DLT is only a slice of pipeline-backed
//     compute (DBSQL MVs etc. dominate — plan §0) so nobody reads the total
//     as "DLT spend".
//   - Distinct pipeline count + the metadata-unavailable KPI (plan §3.5).
//     The latter counts only DLT/SQL/Online-Table pipelines that *should*
//     carry a `system.lakeflow.pipelines` snapshot — Vector Search etc. are
//     excluded server-side so the number stays meaningful, rendered neutral
//     (not alarming).
//   - Top-5 costliest pipelines with their workload badge.
//
// `selectedWorkloads` narrows every figure to the active chip selection
// (plan §3.1 — narrowing only, never dropping spend) so the strip stays in
// lock-step with the table.

import {
  Activity,
  Cloud,
  DollarSign,
  FileQuestion,
  Layers,
  Workflow,
} from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { ErrorState } from '@/components/ui/error-state';
import { Badge } from '@/components/ui/badge';
import { usePipelineSummary, useTopPipelines } from '@/hooks/usePipelines';
import { formatCurrency, workloadBadgeClasses } from '@/lib/pipeline-display';
import type { DateRange } from '@/types/job-spend';
import { useCloudPlatform } from '@/contexts/CloudPlatformContext';
import { useIsAws, AWS_CLOUD_LABEL } from '@/hooks/useCloudGate';
import { formatCalendarDate } from '@/lib/utils';

interface PipelineSummaryCardsProps {
  dateRange: DateRange;
  selectedWorkloads: string[];
}

const integerFormatter = new Intl.NumberFormat('en-US');
// Composite key: `pipeline_id` alone can collide across workspaces (plan §2.2).
const pkey = (p: { workspace_id?: string | null; pipeline_id: string }) =>
  `${p.workspace_id ?? ''}:${p.pipeline_id}`;
const formatNumber = (n: number) => integerFormatter.format(n);
const formatPercent = (part: number, whole: number) =>
  whole > 0 ? `${Math.round((part / whole) * 100)}%` : '0%';

export const PipelineSummaryCards = ({
  dateRange,
  selectedWorkloads,
}: PipelineSummaryCardsProps) => {
  const { config: cloudConfig } = useCloudPlatform();
  const isAws = useIsAws();
  const cloudLabel = isAws
    ? AWS_CLOUD_LABEL
    : `${cloudConfig?.compute_service || 'Cloud'} Cost`;
  const workloadFilter =
    selectedWorkloads.length > 0 ? selectedWorkloads : undefined;
  const {
    data: metrics,
    isLoading: isMetricsLoading,
    isError: isMetricsError,
    refetch: refetchMetrics,
  } = usePipelineSummary(dateRange, workloadFilter);
  const {
    data: topPipelines,
    isLoading: isTopLoading,
    isError: isTopError,
    refetch: refetchTop,
  } = useTopPipelines(dateRange, 5, workloadFilter);

  // Metrics-derived values are computed null-safely so the metrics-dependent
  // sections (KPI strip + compute-mode footnote + workload breakdown) render
  // skeletons/errors independently from the top-5 list below (poly3 — no
  // whole-strip block).
  //
  // Whole-tab landed-day run-rate. Dividing by the selected calendar span
  // would understate the average whenever the newest billing day has not
  // landed yet; freshness is disclosed below.
  const dailyAverageSpend = metrics
    ? metrics.total_spend / Math.max(metrics.data_days, 1)
    : 0;

  // Sort the workload breakdown by $ descending so the dominant workload
  // leads — this is the line that proves "the total is NOT all DLT".
  const workloadEntries = metrics
    ? Object.entries(metrics.workload_breakdown).sort((a, b) => b[1] - a[1])
    : [];

  const hasMetadataGap = !!metrics && metrics.metadata_unavailable > 0;
  const cloudRelevant =
    !!metrics &&
    (metrics.classic_pipelines > 0 ||
      metrics.mixed_pipelines > 0 ||
      metrics.total_cloud_cost != null);

  // CP3: classic + mixed pipelines now carry EC2/EBS cloud cost, so the
  // headline is total spend (DBU + cloud), not DBU alone. `total_cloud_cost`
  // is NULL when every matched pipeline is fully serverless (no separate VM
  // line) — surfaced as "—" + note, not a misleading $0 (plan §5).
  const cloudCost = metrics?.total_cloud_cost;
  const cloudPctOfTotal =
    metrics && cloudCost != null && metrics.total_spend > 0
      ? formatPercent(cloudCost, metrics.total_spend)
      : null;

  return (
    <div className="space-y-6">
      {/* KPI cards: Total Spend / EC2-EBS cloud / Pipelines /
          Metadata unavailable */}
      {isMetricsLoading ? (
        <KpiStripSkeleton />
      ) : isMetricsError ? (
        <ErrorState
          message="Couldn't load pipeline compute summary metrics. Please try again."
          onRetry={() => refetchMetrics()}
        />
      ) : !metrics ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
          <Card>
            <CardContent className="p-6">
              <div className="text-center text-muted-foreground">
                No pipeline compute data available for the selected date range
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
              {formatCurrency(dailyAverageSpend)}/landed-day avg
              {(metrics.dbu_in_non_covered_workspaces ?? 0) > 0 && (
                <>
                  {' '}
                  · {formatCurrency(metrics.dbu_in_non_covered_workspaces ?? 0)}{' '}
                  DBU in non-covered workspaces
                </>
              )}
            </p>
            <p className="text-[11px] text-muted-foreground mt-1">
              Includes all known DBU; cloud cost is included where available.
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
                  {cloudPctOfTotal} of total · classic VM cost (DBU is{' '}
                  {formatCurrency(metrics.total_databricks_cost)})
                </p>
              </>
            ) : (
              <>
                <div
                  className="text-2xl font-bold text-muted-foreground cursor-help"
                  title={
                    cloudRelevant
                      ? 'No cloud cost was returned for this selection. DBU remains included in Total Spend.'
                      : 'No matched pipeline carries a separate VM line in this window — serverless DBU already bundles infrastructure cost.'
                  }
                >
                  —
                </div>
                <p className="text-xs text-muted-foreground mt-1">
                  {cloudRelevant
                    ? 'cloud cost unavailable for this selection'
                    : 'serverless-only — no separate VM line'}
                </p>
              </>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Pipelines</CardTitle>
            <Layers className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-purple-600">
              {formatNumber(metrics.total_pipelines)}
            </div>
            <p className="text-xs text-muted-foreground mt-1">
              {formatNumber(metrics.serverless_pipelines)} serverless ·{' '}
              {formatNumber(metrics.classic_pipelines)} classic
              {metrics.mixed_pipelines > 0 &&
                ` · ${formatNumber(metrics.mixed_pipelines)} mixed`}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">
              Metadata Unavailable
            </CardTitle>
            <FileQuestion
              className={`h-4 w-4 ${
                hasMetadataGap ? 'text-amber-500' : 'text-muted-foreground'
              }`}
            />
          </CardHeader>
          <CardContent>
            <div
              className={`text-2xl font-bold ${
                hasMetadataGap ? 'text-amber-600' : 'text-muted-foreground'
              }`}
              title="DLT / DBSQL MV / Online Table pipelines that should carry a system.lakeflow.pipelines snapshot but don't. Vector Search etc. are excluded — they never carry metadata, so their absence is expected."
            >
              {formatNumber(metrics.metadata_unavailable)}
            </div>
            <p className="text-xs text-muted-foreground mt-1">
              metadata-bearing pipelines missing a snapshot
            </p>
          </CardContent>
        </Card>
      </div>
      )}

      {metrics && (
        <Card>
          <CardContent className="p-4">
            <div className="grid gap-3 text-xs md:grid-cols-3">
              <FreshnessItem
                label="Latest landed data"
                date={metrics.latest_data_date}
                days={metrics.data_days}
                selectedDays={metrics.date_range_days}
                expectedEnd={dateRange.end_date}
              />
              <FreshnessItem
                label="Latest DBU data"
                date={metrics.latest_dbu_date}
                days={metrics.data_days}
                selectedDays={metrics.date_range_days}
                expectedEnd={dateRange.end_date}
              />
              {cloudRelevant ? (
                <FreshnessItem
                  label="Latest cloud data"
                  date={metrics.latest_cloud_date}
                  days={metrics.cloud_data_days}
                  selectedDays={metrics.date_range_days}
                  expectedEnd={dateRange.end_date}
                />
              ) : (
                <div className="text-muted-foreground">
                  <div className="font-medium text-foreground">Cloud data</div>
                  No separate cloud line is expected for this serverless-only
                  selection.
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Compute-mode $ split footnote — three buckets summing to total so the
          wording stays exact even when mixed rows exist (plan §3.2 / §5.3).
          CP3: classic/mixed now include EC2/EBS cloud cost; serverless is the
          full cost because its DBU rate already bundles infrastructure. */}
      {metrics && (
      <Card>
        <CardContent className="p-4">
          <p className="text-xs text-muted-foreground leading-relaxed">
            <span className="font-medium text-foreground">
              {formatPercent(metrics.serverless_spend, metrics.total_spend)}
            </span>{' '}
            of shown spend ({formatCurrency(metrics.serverless_spend)}) is
            serverless (full cost — VM bundled in the DBU rate);{' '}
            <span className="font-medium text-foreground">
              {formatPercent(metrics.classic_spend, metrics.total_spend)}
            </span>{' '}
            ({formatCurrency(metrics.classic_spend)}) is classic (DBU +
            available cloud)
            {metrics.mixed_spend > 0 && (
              <>
                ;{' '}
                <span className="font-medium text-foreground">
                  {formatPercent(metrics.mixed_spend, metrics.total_spend)}
                </span>{' '}
                ({formatCurrency(metrics.mixed_spend)}) is mixed (serverless +
                classic DBU + available cloud)
              </>
            )}
            .
          </p>
        </CardContent>
      </Card>
      )}

      {/* Bottom strip: workload breakdown (left) + top-5 pipelines (right) */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Workload-type $ breakdown — the headline truth indicator that the
            total is NOT all DLT (plan §0 / §3.1). */}
        <Card>
          <CardHeader>
            <CardTitle className="text-lg flex items-center gap-2">
              <Workflow className="h-5 w-5 text-muted-foreground" />
              Spend by Workload
            </CardTitle>
          </CardHeader>
          <CardContent>
            {isMetricsLoading ? (
              <BreakdownSkeleton />
            ) : isMetricsError ? (
              <ErrorState
                compact
                message="Couldn't load workload breakdown."
                onRetry={() => refetchMetrics()}
              />
            ) : !metrics ? (
              <div className="text-center text-muted-foreground py-4 text-sm">
                No data available
              </div>
            ) : workloadEntries.length > 0 ? (
              <div className="space-y-3">
                {workloadEntries.map(([workload, cost]) => (
                  <div
                    key={workload}
                    className="flex items-center justify-between gap-2"
                  >
                    <Badge
                      variant="secondary"
                      className={`text-[10px] shrink-0 ${workloadBadgeClasses(
                        workload,
                      )}`}
                    >
                      {workload}
                    </Badge>
                    <div className="text-right shrink-0">
                      <div className="text-sm font-semibold">
                        {formatCurrency(cost)}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {formatPercent(cost, metrics.total_spend)}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-center text-muted-foreground py-4 text-sm">
                No workload data for this period
              </div>
            )}
          </CardContent>
        </Card>

        {/* Top 5 Costliest Pipelines */}
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle className="text-lg">
              Top 5 Costliest Pipelines
            </CardTitle>
          </CardHeader>
          <CardContent>
            {isTopLoading ? (
              <TopListSkeleton />
            ) : isTopError ? (
              <ErrorState
                compact
                message="Couldn't load top pipelines."
                onRetry={() => refetchTop()}
              />
            ) : topPipelines && topPipelines.length > 0 ? (
              <div className="space-y-3">
                {topPipelines.map((pipeline, index) => {
                  const hasName =
                    !!pipeline.pipeline_name &&
                    pipeline.pipeline_name.trim().length > 0;
                  const label = hasName
                    ? pipeline.pipeline_name!
                    : `Pipeline ${pipeline.pipeline_id}`;
                  return (
                    <div
                      key={pkey(pipeline)}
                      className="flex justify-between items-center gap-2"
                    >
                      <div className="flex items-center space-x-2 min-w-0">
                        <span className="text-xs bg-muted text-muted-foreground px-2 py-1 rounded shrink-0">
                          #{index + 1}
                        </span>
                        <span
                          className={`text-sm font-medium truncate ${
                            hasName ? '' : 'font-mono text-muted-foreground'
                          }`}
                          title={
                            hasName
                              ? `${label} — ${pipeline.pipeline_id}`
                              : `Unnamed — ${pipeline.pipeline_id}`
                          }
                        >
                          {label}
                        </span>
                        <Badge
                          variant="secondary"
                          className={`text-[10px] shrink-0 ${workloadBadgeClasses(
                            pipeline.workload_type,
                          )}`}
                        >
                          {pipeline.workload_type}
                        </Badge>
                        {pipeline.workspace_covered === false && (
                          <Badge
                            variant="outline"
                            className="text-[10px] shrink-0 border-amber-300 text-amber-700 dark:text-amber-300"
                            title="DBU is included, but cloud billing coverage is incomplete for this workspace."
                          >
                            Not covered
                          </Badge>
                        )}
                      </div>
                      <div className="text-right shrink-0 ml-2">
                        <div className="text-sm font-semibold">
                          {formatCurrency(pipeline.total_cost)}
                        </div>
                        <div className="text-xs text-muted-foreground">
                          {pipeline.active_days} day
                          {pipeline.active_days === 1 ? '' : 's'}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <EmptyTopList label="No pipelines found for this period" />
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

const FreshnessItem = ({
  label,
  date,
  days,
  selectedDays,
  expectedEnd,
}: {
  label: string;
  date?: string | null;
  days?: number;
  selectedDays: number;
  expectedEnd: string;
}) => {
  const complete =
    !!date &&
    days != null &&
    selectedDays > 0 &&
    days >= selectedDays &&
    date >= expectedEnd;

  return (
    <div className="text-muted-foreground">
      <div className="font-medium text-foreground">{label}</div>
      <div>
        {date ? formatCalendarDate(date) : 'Date unavailable'}
        {' · '}
        {days != null
          ? `${days} of ${selectedDays} selected days`
          : 'day count unavailable'}
      </div>
      <div
        className={
          complete
            ? 'text-emerald-700 dark:text-emerald-300'
            : 'text-amber-700 dark:text-amber-300'
        }
      >
        {complete ? 'Selected window landed' : 'Completeness not confirmed'}
      </div>
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
  <div className="space-y-3">
    {[...Array(4)].map((_, i) => (
      <div key={i} className="flex items-center justify-between">
        <Skeleton className="h-4 w-[80px]" />
        <Skeleton className="h-4 w-[60px]" />
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
