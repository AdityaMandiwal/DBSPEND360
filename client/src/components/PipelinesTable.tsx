// By-Pipeline table for the Pipeline Compute tab with single-level row
// expansion (plan §3.3 / §5.2 / CP10):
//
//   Level 0 (pipeline row)    — one row per pipeline in the window with
//                               denormalized metadata from
//                               `system.lakeflow.pipelines`. Carries three
//                               truth indicators: the `workload_type` badge,
//                               the `compute_mode` badge, and the
//                               `cost_basis` info-icon on the `$` (shown only
//                               for dbu_only/partial — plan §3.2). The §3.5
//                               neutral three-state metadata badge sits under
//                               the name. Pipeline name is clickable and opens
//                               `PipelineDetailsModal`.
//   Level 1 (pipeline → day)  — expand the pipeline row to see per-day DBU /
//                               total rows (the rollup's product grain is
//                               summed away server-side — plan §5.2 — so the
//                               UI sees exactly one row per pipeline-day).
//
// There is intentionally NO second drill level (no per-update in v1 — plan
// §3.6 / §13) and the per-day cost_basis is collapsed to a single label.

import { Fragment, useEffect, useState } from 'react';
import {
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronRight as ChevronRightIcon,
  Info,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { usePipelines } from '@/hooks/usePipelines';
import {
  cloudMissingNote,
  computeModeClasses,
  costBasisCaveat,
  MIXED_CLOUD_NOTE,
  workloadBadgeClasses,
} from '@/lib/pipeline-display';
import type { GroupedPipeline, PipelineDailySpend } from '@/types/pipeline';
import type { DateRange } from '@/types/job-spend';
import { useCloudPlatform } from '@/contexts/CloudPlatformContext';
import { useIsAws, AWS_CLOUD_LABEL } from '@/hooks/useCloudGate';
import { PipelineDetailsModal } from './PipelineDetailsModal';

interface PipelinesTableProps {
  dateRange: DateRange;
  searchTerm: string;
  selectedWorkloads: string[];
}

const currencyFormatter = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
const formatCurrency = (amount: number) => currencyFormatter.format(amount);

const formatDate = (dateStr: string) => {
  try {
    // Append `T00:00:00` so an ISO date (YYYY-MM-DD) parse stays
    // calendar-stable on negative-offset zones (mirrors the pool table).
    return new Date(`${dateStr}T00:00:00`).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    });
  } catch {
    return dateStr;
  }
};

const formatBadgeDate = (dateStr?: string | null): string | null => {
  if (!dateStr) return null;
  try {
    return new Date(dateStr).toISOString().slice(0, 10);
  } catch {
    return dateStr;
  }
};

const PAGE_SIZE = 25;

// EC2/EBS cloud cell (plan §3.4 / §5). Renders the real $ when known
// (including a genuine `$0.00`), or "—" + a typed note when the value is NULL
// — distinguishing "no separate VM line by design" (serverless) from "data
// not landed yet" (classic). A `mixed` row that carries a number gets an info
// icon flagging that the figure is the classic portion only.
const CloudCostCell = ({
  cloudCost,
  isServerless,
  isMixed,
}: {
  cloudCost?: number | null;
  isServerless: boolean;
  isMixed: boolean;
}) => {
  if (cloudCost == null) {
    const note = cloudMissingNote(isServerless);
    return (
      <span
        className="text-muted-foreground cursor-help"
        title={note}
        aria-label={note}
      >
        —
      </span>
    );
  }
  return (
    <span className="inline-flex items-center justify-end gap-1">
      {formatCurrency(cloudCost)}
      {isMixed && (
        <span
          className="inline-flex text-amber-500"
          title={MIXED_CLOUD_NOTE}
          aria-label={MIXED_CLOUD_NOTE}
        >
          <Info className="h-3.5 w-3.5 shrink-0" />
        </span>
      )}
    </span>
  );
};

export const PipelinesTable = ({
  dateRange,
  searchTerm,
  selectedWorkloads,
}: PipelinesTableProps) => {
  const { config: cloudConfig } = useCloudPlatform();
  const isAws = useIsAws();
  // Pipeline cloud cost is a single EC2/EBS bucket (no compute/storage/network
  // segmentation — the cluster explorer's product split isn't carried into the
  // pipeline rollup), so we always render ONE cloud column. Only the label is
  // platform-aware (plan §3.4 / §1.4): `EC2 / EBS` on AWS, otherwise the
  // provider's generic compute-service name.
  const cloudLabel = isAws
    ? AWS_CLOUD_LABEL
    : `Total ${cloudConfig?.compute_service || 'Cloud'}`;
  const [page, setPage] = useState(1);
  const [expandedPipelines, setExpandedPipelines] = useState<Set<string>>(
    new Set(),
  );
  const [activeModal, setActiveModal] = useState<GroupedPipeline | null>(null);

  // Reset to page 1 when any filter changes so the user doesn't land on an
  // out-of-range page after the result set shrinks (mirrors the pool table).
  useEffect(() => {
    setPage(1);
  }, [
    searchTerm,
    dateRange.start_date,
    dateRange.end_date,
    selectedWorkloads.join(','),
  ]);

  const { data, isLoading, isFetching, error } = usePipelines({
    start_date: dateRange.start_date,
    end_date: dateRange.end_date,
    search: searchTerm || undefined,
    workload_type: selectedWorkloads.length > 0 ? selectedWorkloads : undefined,
    page,
    per_page: PAGE_SIZE,
  });

  const isInitialLoading = isLoading && !data;
  const isBackgroundFetching = isFetching && !!data;

  const rows = data?.data ?? [];
  const totalCount = data?.total_count ?? 0;
  const totalPages = data?.total_pages ?? 0;

  const togglePipeline = (pipelineId: string) => {
    setExpandedPipelines((prev) => {
      const next = new Set(prev);
      if (next.has(pipelineId)) next.delete(pipelineId);
      else next.add(pipelineId);
      return next;
    });
  };

  // 8 data columns (incl. EC2/EBS cloud) + 1 expander.
  const columnCount = 9;

  return (
    <div className="space-y-4">
      <div className="rounded-md border relative overflow-hidden">
        {isBackgroundFetching && (
          <div
            className="absolute left-0 right-0 top-0 h-0.5 bg-blue-500/70 animate-pulse z-10"
            aria-hidden="true"
          />
        )}
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-10 px-2" />
              <TableHead className="px-4">Pipeline</TableHead>
              <TableHead className="px-4">Workload</TableHead>
              <TableHead className="px-4">Compute</TableHead>
              <TableHead className="px-4">Creator</TableHead>
              <TableHead className="px-4 text-right">Active Days</TableHead>
              <TableHead className="px-4 text-right">{cloudLabel}</TableHead>
              <TableHead className="px-4 text-right">DBU Cost</TableHead>
              <TableHead className="px-4 text-right">Total Cost</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {error ? (
              <TableRow>
                <TableCell colSpan={columnCount} className="h-24 text-center">
                  <div className="text-red-600 font-medium mb-1">
                    Error loading pipeline compute data
                  </div>
                  <div className="text-sm text-muted-foreground">
                    {error.message}
                  </div>
                </TableCell>
              </TableRow>
            ) : isInitialLoading ? (
              [...Array(8)].map((_, i) => (
                <TableRow key={i}>
                  {[...Array(columnCount)].map((_, j) => (
                    <TableCell key={j} className="px-4">
                      <Skeleton className="h-8 w-full" />
                    </TableCell>
                  ))}
                </TableRow>
              ))
            ) : rows.length > 0 ? (
              rows.map((pipeline) => {
                const isExpanded = expandedPipelines.has(pipeline.pipeline_id);
                const hasName =
                  !!pipeline.pipeline_name &&
                  pipeline.pipeline_name.trim().length > 0;
                const displayName = hasName
                  ? pipeline.pipeline_name!
                  : `Pipeline ${pipeline.pipeline_id}`;
                const caveat = costBasisCaveat(pipeline.cost_basis);
                return (
                  <Fragment key={pipeline.pipeline_id}>
                    <TableRow className="hover:bg-muted/50">
                      <TableCell className="px-2">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => togglePipeline(pipeline.pipeline_id)}
                          className="h-8 w-8 p-0"
                          aria-label={
                            isExpanded
                              ? 'Collapse pipeline'
                              : 'Expand pipeline'
                          }
                        >
                          {isExpanded ? (
                            <ChevronDown className="h-4 w-4" />
                          ) : (
                            <ChevronRightIcon className="h-4 w-4" />
                          )}
                        </Button>
                      </TableCell>
                      <TableCell className="px-4 max-w-[280px]">
                        <button
                          type="button"
                          onClick={() => setActiveModal(pipeline)}
                          className="text-left truncate font-medium text-blue-600 hover:text-blue-800 hover:underline"
                          title={`View details for ${pipeline.pipeline_id}`}
                        >
                          <span className={hasName ? '' : 'font-mono'}>
                            {displayName}
                          </span>
                        </button>
                        <div
                          className="text-xs text-muted-foreground font-mono truncate"
                          title={pipeline.pipeline_id}
                        >
                          {pipeline.pipeline_id}
                        </div>
                        <PipelineStateBadge pipeline={pipeline} />
                      </TableCell>
                      <TableCell className="px-4">
                        <Badge
                          variant="secondary"
                          className={`text-[10px] ${workloadBadgeClasses(
                            pipeline.workload_type,
                          )}`}
                        >
                          {pipeline.workload_type}
                        </Badge>
                      </TableCell>
                      <TableCell className="px-4">
                        <Badge
                          variant="secondary"
                          className={`text-[10px] capitalize ${computeModeClasses(
                            pipeline.compute_mode,
                          )}`}
                        >
                          {pipeline.compute_mode}
                        </Badge>
                      </TableCell>
                      <TableCell className="px-4 max-w-[180px]">
                        <div
                          className="text-xs truncate"
                          title={pipeline.created_by ?? undefined}
                        >
                          {pipeline.created_by ?? (
                            <span className="italic text-muted-foreground">
                              Unknown
                            </span>
                          )}
                        </div>
                      </TableCell>
                      <TableCell className="px-4 text-right text-sm">
                        {pipeline.active_days}
                      </TableCell>
                      <TableCell className="px-4 text-right font-medium text-blue-600">
                        <CloudCostCell
                          cloudCost={pipeline.total_cloud_cost}
                          isServerless={pipeline.compute_mode === 'serverless'}
                          isMixed={pipeline.compute_mode === 'mixed'}
                        />
                      </TableCell>
                      <TableCell className="px-4 text-right font-medium text-red-600">
                        <span className="inline-flex items-center justify-end gap-1">
                          {formatCurrency(pipeline.total_databricks_cost)}
                          {caveat && (
                            <span
                              className="inline-flex text-amber-500"
                              title={caveat}
                              aria-label={caveat}
                            >
                              <Info className="h-3.5 w-3.5 shrink-0" />
                            </span>
                          )}
                        </span>
                      </TableCell>
                      <TableCell className="px-4 text-right">
                        <div className="font-bold text-lg">
                          {formatCurrency(pipeline.total_cost)}
                        </div>
                        {pipeline.total_cost > 1000 && (
                          <Badge variant="destructive" className="text-xs">
                            High Cost
                          </Badge>
                        )}
                      </TableCell>
                    </TableRow>
                    {isExpanded && (
                      <TableRow
                        key={`${pipeline.pipeline_id}-expanded`}
                        className="bg-muted/30"
                      >
                        <TableCell colSpan={columnCount} className="p-0">
                          <PipelineDayBreakdown
                            pipeline={pipeline}
                            cloudLabel={cloudLabel}
                          />
                        </TableCell>
                      </TableRow>
                    )}
                  </Fragment>
                );
              })
            ) : (
              <TableRow>
                <TableCell colSpan={columnCount} className="h-24 text-center">
                  <div className="text-muted-foreground">
                    No pipelines found for the selected filters.
                  </div>
                  <div className="text-xs text-muted-foreground mt-2">
                    Try widening the date range or clearing the workload
                    filter.
                  </div>
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      {totalCount > 0 && (
        <div className="flex items-center justify-between">
          <div className="text-sm text-muted-foreground">
            Showing {rows.length} pipeline{rows.length === 1 ? '' : 's'} of{' '}
            {totalCount} total
            {searchTerm && ` (filtered by "${searchTerm}")`}
          </div>

          <div className="flex items-center space-x-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1 || isInitialLoading}
            >
              <ChevronLeft className="h-4 w-4 mr-1" /> Previous
            </Button>
            <div className="text-sm font-medium flex items-center gap-2">
              <span>
                Page {page} of {Math.max(totalPages, 1)}
              </span>
              {isBackgroundFetching && (
                <span
                  className="text-xs text-muted-foreground"
                  aria-live="polite"
                >
                  Updating…
                </span>
              )}
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setPage((p) => p + 1)}
              disabled={page >= totalPages || isInitialLoading}
            >
              Next <ChevronRight className="h-4 w-4 ml-1" />
            </Button>
          </div>
        </div>
      )}

      {activeModal && (
        <PipelineDetailsModal
          pipelineId={activeModal.pipeline_id}
          workspaceId={activeModal.workspace_id}
          isOpen
          onClose={() => setActiveModal(null)}
        />
      )}
    </div>
  );
};

// Plan §3.5 badge — three states, neutral and product-aware:
//   - active                    : no badge
//   - "Deleted YYYY-MM-DD"        : snapshot exists but `delete_time` set (yellow)
//   - "Metadata not available"    : no `system.lakeflow.pipelines` row — the
//                                   *expected* state for Vector Search etc.,
//                                   rendered NEUTRAL grey (not alarming)
const PipelineStateBadge = ({ pipeline }: { pipeline: GroupedPipeline }) => {
  if (pipeline.pipeline_deleted_at) {
    const dateLabel = formatBadgeDate(pipeline.pipeline_deleted_at);
    return (
      <Badge
        variant="secondary"
        className="mt-1 text-[10px] bg-amber-100 text-amber-700 hover:bg-amber-100 dark:bg-amber-500/15 dark:text-amber-300 dark:hover:bg-amber-500/15"
        title="Pipeline was deleted; metadata is as of that date. Cost data is still accurate."
      >
        Deleted {dateLabel}
      </Badge>
    );
  }
  if (pipeline.metadata_missing) {
    return (
      <Badge
        variant="secondary"
        className="mt-1 text-[10px] bg-muted text-muted-foreground hover:bg-muted"
        title="No row in system.lakeflow.pipelines — normal for Vector Search / cross-region / retention edge. Cost data is still accurate."
      >
        Metadata not available
      </Badge>
    );
  }
  return null;
};

// Per-day expansion panel for one pipeline. Renders one row per usage_date.
// The §9 invariant "sum of days[].total_cost == pipeline total_cost" is
// structural (plan §5.2), so no separate reconciliation is shown.
const PipelineDayBreakdown = ({
  pipeline,
  cloudLabel,
}: {
  pipeline: GroupedPipeline;
  cloudLabel: string;
}) => {
  if (pipeline.days.length === 0) {
    return (
      <div className="p-4 border-l-4 border-l-blue-500 bg-muted/20 text-sm text-muted-foreground">
        No daily breakdown returned for this pipeline.
      </div>
    );
  }

  return (
    <div className="p-4 border-l-4 border-l-blue-500 bg-muted/20">
      <h4 className="font-semibold text-sm text-muted-foreground mb-3">
        Daily breakdown ({pipeline.days.length} day
        {pipeline.days.length === 1 ? '' : 's'})
      </h4>
      <div className="space-y-2">
        {[...pipeline.days]
          .sort((a, b) => a.usage_date.localeCompare(b.usage_date))
          .map((day) => (
            <DayRow
              key={`${pipeline.pipeline_id}|${day.usage_date}`}
              day={day}
              cloudLabel={cloudLabel}
            />
          ))}
      </div>
    </div>
  );
};

const DayRow = ({
  day,
  cloudLabel,
}: {
  day: PipelineDailySpend;
  cloudLabel: string;
}) => {
  const caveat = costBasisCaveat(day.cost_basis);
  return (
    <div className="rounded-md border bg-background overflow-hidden">
      <div className="flex items-center justify-between p-3">
        <div className="flex items-center space-x-3">
          <div className="text-sm font-medium">{formatDate(day.usage_date)}</div>
          {caveat && (
            <Badge
              variant="secondary"
              className="text-[10px] bg-amber-100 text-amber-700 hover:bg-amber-100 dark:bg-amber-500/15 dark:text-amber-300 dark:hover:bg-amber-500/15"
              title={caveat}
            >
              DBU only
            </Badge>
          )}
        </div>
        <div className="flex items-center space-x-4">
          <div className="text-sm text-blue-600">
            {cloudLabel}:{' '}
            <CloudCostCell
              cloudCost={day.cloud_cost}
              isServerless={day.cost_basis === 'full'}
              isMixed={day.cost_basis === 'partial'}
            />
          </div>
          <div className="text-sm text-red-600">
            DBU: {formatCurrency(day.databricks_cost)}
          </div>
          <div className="text-sm font-semibold">
            Total: {formatCurrency(day.total_cost)}
          </div>
        </div>
      </div>
    </div>
  );
};
