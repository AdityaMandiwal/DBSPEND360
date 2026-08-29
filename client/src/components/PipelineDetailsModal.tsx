// Pipeline details modal — renders pipeline config + pipeline-tuned LLM
// analysis (plan §4.1 / CP10).
//
// Distinct from `ClusterDetailsModal` / `InstancePoolDetailsModal` because the
// upstream source is `system.lakeflow.pipelines` (not clusters/pools) and the
// LLM prompt is fed workload and cost context. Its fixed 180-day lookback is
// disclosed separately from the selected table window.
//
// Renders the §3.5 three-state info banner at the top:
//   - Active                  : no banner.
//   - Deleted (visible)       : yellow "Pipeline deleted on YYYY-MM-DD."
//   - Metadata not available  : NEUTRAL grey banner (not alarming) — the
//                               expected state for Vector Search / cross-region
//                               (plan §3.5). DBU stays available; config
//                               analysis is degraded.
//
// `created_by` / `run_as` are human-readable values straight from the system
// table — no GUID resolution, no REST API (plan §3.4, the key simplification
// over the Instance Pools modal).

import {
  AlertTriangle,
  Brain,
  Cloud,
  DollarSign,
  FileQuestion,
  Info,
  User,
  Workflow,
} from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  usePipelineAnalysis,
  usePipelineDetails,
} from '@/hooks/usePipelines';
import {
  computeModeClasses,
  costBasisCaveat,
  workloadBadgeClasses,
  cloudMissingNote,
  formatCurrency,
} from '@/lib/pipeline-display';
import { useAiModelLabel } from '@/hooks/useJobSpends';
import { ApiError } from '@/lib/api-client';
import { closeOnly, formatCalendarDate } from '@/lib/utils';
import { AnalysisMarkdown } from './AnalysisMarkdown';
import { CloudCostCell } from './CloudCostCell';
import type { DateRange } from '@/types/job-spend';
import type { GroupedPipeline } from '@/types/pipeline';

interface PipelineDetailsModalProps {
  pipeline: GroupedPipeline;
  dateRange: DateRange;
  isOpen: boolean;
  onClose: () => void;
}

// `pipeline_deleted_at` is a timestamp; `formatCalendarDate` renders its LOCAL
// calendar day so the banner never shows the wrong date on negative-UTC zones.
const formatDeleteDate = (dateStr?: string | null): string | null =>
  dateStr
    ? formatCalendarDate(dateStr, {
        year: 'numeric',
        month: 'long',
        day: 'numeric',
      })
    : null;

export const PipelineDetailsModal = ({
  pipeline,
  dateRange,
  isOpen,
  onClose,
}: PipelineDetailsModalProps) => {
  const { pipeline_id: pipelineId, workspace_id: workspaceId } = pipeline;
  const {
    data: details,
    isLoading: detailsLoading,
    error: detailsError,
  } = usePipelineDetails(pipelineId, workspaceId);
  // Only fire the (LLM-charging) analysis once details resolve successfully,
  // so an ambiguous (409) or failed pipeline never charges analysis
  // (plan §7.1).
  const detailsResolved = !!details && !detailsError;
  const aiModelLabel = useAiModelLabel();
  const {
    data: analysis,
    isLoading: analysisLoading,
    error: analysisError,
  } = usePipelineAnalysis(pipelineId, workspaceId, {
    enabled: detailsResolved,
  });

  // A 409 means the pipeline_id spans >1 workspace and no workspace_id was
  // supplied — render a disambiguation hint rather than a raw error. The
  // table always passes workspace_id, so this is an edge case (e.g. a
  // deep-link), but we still want it to be self-explanatory (plan §7.1).
  const isAmbiguous =
    detailsError instanceof ApiError && detailsError.status === 409;

  const deletedDateLabel = formatDeleteDate(details?.pipeline_deleted_at);
  const caveat = costBasisCaveat(
    details?.cost_basis ?? pipeline.cost_basis,
    pipeline.total_cloud_cost,
    pipeline.workspace_covered,
  );

  return (
    <Dialog open={isOpen} onOpenChange={closeOnly(onClose)}>
      <DialogContent className="max-w-5xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="text-xl font-semibold flex items-center gap-2">
            <Workflow className="h-5 w-5" />
            Pipeline Configuration & Analysis
          </DialogTitle>
        </DialogHeader>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-lg">
              <DollarSign className="h-5 w-5" />
              Selected Window Spend
            </CardTitle>
            <p className="text-xs text-muted-foreground">
              {formatCalendarDate(dateRange.start_date)} to{' '}
              {formatCalendarDate(dateRange.end_date)}
            </p>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              <div>
                <div className="text-xs text-muted-foreground">DBU</div>
                <div className="font-semibold text-red-600">
                  {formatCurrency(pipeline.total_databricks_cost)}
                </div>
              </div>
              <div>
                <div className="flex items-center gap-1 text-xs text-muted-foreground">
                  <Cloud className="h-3.5 w-3.5" /> Cloud
                </div>
                <div className="font-semibold text-blue-600">
                  <CloudCostCell
                    value={pipeline.total_cloud_cost}
                    workspaceCovered={pipeline.workspace_covered}
                    missingNote={cloudMissingNote(
                      pipeline.compute_mode === 'serverless',
                    )}
                  />
                </div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">Total</div>
                <div className="font-bold">
                  {formatCurrency(pipeline.total_cost)}
                </div>
              </div>
            </div>
            <div
              className={`mt-3 text-xs ${
                pipeline.workspace_covered === false
                  ? 'text-amber-700 dark:text-amber-300'
                  : 'text-muted-foreground'
              }`}
            >
              {pipeline.workspace_covered === false
                ? pipeline.total_cloud_cost != null
                  ? 'Cloud billing coverage is partial. DBU is included; treat the available cloud amount and Total as partial.'
                  : 'Not covered for cloud billing. DBU is included, but cloud cost is unavailable and Total excludes it.'
                : 'Cloud billing coverage is available; “—” means no separate cloud line was returned.'}
            </div>
          </CardContent>
        </Card>

        {detailsError ? (
          isAmbiguous ? (
            <div className="mx-auto max-w-lg py-8 space-y-3 text-center">
              <FileQuestion className="mx-auto h-8 w-8 text-muted-foreground" />
              <div className="font-medium text-foreground">
                This pipeline ID exists in more than one workspace
              </div>
              <div className="text-sm text-muted-foreground">
                {detailsError.message}
              </div>
              <div className="text-xs text-muted-foreground">
                Open the pipeline from its row in the table (which carries the
                workspace) to see its configuration and analysis.
              </div>
            </div>
          ) : (
            <div className="text-center py-8">
              <div className="text-red-600 font-medium mb-2">
                Error loading pipeline details
              </div>
              <div className="text-sm text-muted-foreground">
                {detailsError.message}
              </div>
            </div>
          )
        ) : detailsLoading ? (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 py-6">
            <div className="space-y-4">
              <Skeleton className="h-6 w-32" />
              <div className="space-y-3">
                {[...Array(8)].map((_, i) => (
                  <div key={i} className="flex justify-between">
                    <Skeleton className="h-4 w-32" />
                    <Skeleton className="h-4 w-24" />
                  </div>
                ))}
              </div>
            </div>
            <div className="space-y-4">
              <Skeleton className="h-6 w-32" />
              <Skeleton className="h-32 w-full" />
            </div>
          </div>
        ) : details ? (
          <div className="space-y-6 py-6">
            {/* §3.5 three-state info banner. No banner on the active path. */}
            {details.pipeline_deleted_at && (
              <div className="flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-500/40 dark:bg-amber-500/10 dark:text-amber-200">
                <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
                <div>
                  <div className="font-semibold">
                    Pipeline deleted on {deletedDateLabel}.
                  </div>
                  <div className="text-xs mt-1 opacity-90">
                    Configuration shown is as of the delete time. DBU remains
                    included; cloud completeness is disclosed above.
                  </div>
                </div>
              </div>
            )}
            {details.metadata_missing && !details.pipeline_deleted_at && (
              // Neutral grey, NOT alarming — the expected state for Vector
              // Search / cross-region (plan §3.5).
              <div className="flex items-start gap-2 rounded-md border bg-muted px-4 py-3 text-sm text-muted-foreground">
                <FileQuestion className="h-4 w-4 mt-0.5 shrink-0" />
                <div>
                  <div className="font-semibold text-foreground">
                    Metadata not available.
                  </div>
                  <div className="text-xs mt-1">
                    No row found in{' '}
                    <span className="font-mono">
                      system.lakeflow.pipelines
                    </span>{' '}
                    — normal for Vector Search, cross-region pipelines, or
                    retention edges. DBU remains included and cloud
                    completeness is disclosed above; configuration is
                    unavailable.
                  </div>
                </div>
              </div>
            )}

            {/* Cost-basis caveat banner — only for classic / mixed rows whose
                DBU figure alone excludes cloud VM cost (plan §3.2). The VM
                cost itself is now surfaced in the EC2/EBS column (CP3), so the
                banner clarifies where it lives rather than calling it a v2
                gap. */}
            {caveat && (
              <div className="flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-500/40 dark:bg-amber-500/10 dark:text-amber-200">
                <Info className="h-4 w-4 mt-0.5 shrink-0" />
                <div>
                  <div className="font-semibold">{caveat}.</div>
                  <div className="text-xs mt-1 opacity-90">
                    The classic VM cost is shown separately in the EC2/EBS
                    column and is included in Total Cost. Serverless portions
                    have no separate VM line — their DBU rate already bundles
                    infrastructure.
                  </div>
                </div>
              </div>
            )}

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              {/* Pipeline Configuration */}
              <div className="space-y-4">
                <h3 className="text-lg font-semibold flex items-center">
                  <Workflow className="mr-2 h-5 w-5" />
                  Pipeline Configuration
                </h3>

                <div className="p-4 border rounded-lg space-y-3">
                  <div className="flex justify-between items-start">
                    <span className="text-sm font-medium text-muted-foreground">
                      Pipeline Name
                    </span>
                    <div className="text-right max-w-[260px]">
                      <div
                        className="text-sm font-medium truncate"
                        title={details.pipeline_name ?? undefined}
                      >
                        {details.pipeline_name ?? (
                          <span className="font-mono text-muted-foreground">
                            Pipeline {details.pipeline_id}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="flex justify-between items-start">
                    <span className="text-sm font-medium text-muted-foreground">
                      Workspace ID
                    </span>
                    <div
                      className="max-w-[260px] truncate text-right font-mono text-xs"
                      title={details.workspace_id}
                    >
                      {details.workspace_id}
                    </div>
                  </div>

                  <div className="flex justify-between items-start">
                    <span className="text-sm font-medium text-muted-foreground">
                      Pipeline ID
                    </span>
                    <div className="text-right">
                      <div
                        className="font-mono text-xs max-w-[260px] truncate"
                        title={details.pipeline_id}
                      >
                        {details.pipeline_id}
                      </div>
                    </div>
                  </div>

                  <div className="flex justify-between items-start">
                    <span className="text-sm font-medium text-muted-foreground">
                      Workload Type
                    </span>
                    <div className="text-right max-w-[260px]">
                      {details.workload_type ? (
                        <Badge
                          variant="secondary"
                          className={`text-[10px] ${workloadBadgeClasses(
                            details.workload_type,
                          )}`}
                        >
                          {details.workload_type}
                        </Badge>
                      ) : (
                        <span className="text-sm text-muted-foreground">
                          N/A
                        </span>
                      )}
                    </div>
                  </div>

                  <div className="flex justify-between items-start">
                    <span className="text-sm font-medium text-muted-foreground">
                      Compute Mode
                    </span>
                    <div className="text-right max-w-[260px]">
                      {details.compute_mode ? (
                        <Badge
                          variant="secondary"
                          className={`text-[10px] capitalize ${computeModeClasses(
                            details.compute_mode,
                          )}`}
                        >
                          {details.compute_mode}
                        </Badge>
                      ) : (
                        <span className="text-sm text-muted-foreground">
                          N/A
                        </span>
                      )}
                    </div>
                  </div>

                  <div className="flex justify-between items-start">
                    <span className="text-sm font-medium text-muted-foreground">
                      Pipeline Type
                    </span>
                    <div className="text-right">
                      <div className="text-sm font-mono">
                        {details.pipeline_type ?? 'N/A'}
                      </div>
                    </div>
                  </div>
                </div>

                <div className="p-4 border rounded-lg space-y-3">
                  <h4 className="font-semibold flex items-center gap-1">
                    <User className="h-4 w-4" /> Ownership
                  </h4>

                  <div className="flex justify-between items-start">
                    <span className="text-sm font-medium text-muted-foreground">
                      Created By
                    </span>
                    <div className="text-right max-w-[260px]">
                      {details.created_by ? (
                        <div
                          className="text-sm truncate"
                          title={details.created_by}
                        >
                          {details.created_by}
                        </div>
                      ) : (
                        <span className="text-sm italic text-muted-foreground">
                          Unknown
                        </span>
                      )}
                    </div>
                  </div>

                  <div className="flex justify-between items-start">
                    <span className="text-sm font-medium text-muted-foreground">
                      Run As
                    </span>
                    <div className="text-right max-w-[260px]">
                      {details.run_as ? (
                        <div
                          className="text-sm truncate"
                          title={details.run_as}
                        >
                          {details.run_as}
                        </div>
                      ) : (
                        <span className="text-sm italic text-muted-foreground">
                          Unknown
                        </span>
                      )}
                    </div>
                  </div>
                </div>

                {details.tags && Object.keys(details.tags).length > 0 && (
                  <div className="p-4 border rounded-lg space-y-3">
                    <h4 className="font-semibold flex items-center gap-1">
                      <Info className="h-4 w-4" /> Tags
                    </h4>
                    <div className="flex flex-wrap gap-2">
                      {Object.entries(details.tags).map(([k, v]) => (
                        <Badge
                          key={k}
                          variant="outline"
                          className="text-xs font-mono"
                          title={`${k} = ${v}`}
                        >
                          {k}={v}
                        </Badge>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              {/* AI Pipeline Analysis */}
              <div className="space-y-4">
                <Card>
                  <CardHeader>
                    <CardTitle className="flex items-center text-lg">
                      <Brain className="mr-2 h-5 w-5 text-purple-600" />
                      AI Pipeline Analysis
                      <Badge variant="secondary" className="ml-2 text-xs">
                        Powered by {aiModelLabel}
                      </Badge>
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="mb-4 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:border-amber-500/40 dark:bg-amber-500/10 dark:text-amber-200">
                      AI analysis uses a fixed 180-day lookback. It does not use
                      the selected table window shown above.
                    </div>
                    {analysisError ? (
                      <div className="text-center py-4">
                        <div className="text-red-600 font-medium mb-2">
                          Analysis unavailable
                        </div>
                        <div className="text-sm text-muted-foreground">
                          {analysisError.message}
                        </div>
                      </div>
                    ) : analysisLoading ? (
                      <div className="space-y-3">
                        <div className="flex items-center space-x-2">
                          <Skeleton className="h-4 w-4 rounded-full" />
                          <Skeleton className="h-4 w-48" />
                        </div>
                        <Skeleton className="h-24 w-full" />
                        <div className="flex items-center space-x-2">
                          <Skeleton className="h-4 w-4 rounded-full" />
                          <Skeleton className="h-4 w-56" />
                        </div>
                        <Skeleton className="h-20 w-full" />
                      </div>
                    ) : analysis ? (
                      <div className="space-y-4">
                        <AnalysisMarkdown>{analysis.analysis}</AnalysisMarkdown>
                        <div className="text-xs text-muted-foreground border-t pt-2">
                          Generated on{' '}
                          {new Date(analysis.timestamp).toLocaleDateString(
                            'en-US',
                            {
                              year: 'numeric',
                              month: 'long',
                              day: 'numeric',
                            },
                          )}
                        </div>
                      </div>
                    ) : (
                      <div className="text-center py-4">
                        <div className="text-muted-foreground">
                          No analysis available
                        </div>
                      </div>
                    )}
                  </CardContent>
                </Card>
              </div>
            </div>
          </div>
        ) : (
          <div className="text-center py-8">
            <div className="text-muted-foreground">
              No pipeline details available
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
};
