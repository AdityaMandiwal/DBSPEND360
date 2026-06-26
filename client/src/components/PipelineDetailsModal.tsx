// Pipeline details modal — renders pipeline config + pipeline-tuned LLM
// analysis (plan §4.1 / CP10).
//
// Distinct from `ClusterDetailsModal` / `InstancePoolDetailsModal` because the
// upstream source is `system.lakeflow.pipelines` (not clusters/pools) and the
// LLM prompt is fed `workload_type` + `cost_basis` so the analysis carries the
// DBU-only caveat iff the number excludes cloud VM cost (plan §3.2 / §9 /
// CP7).
//
// Renders the §3.5 three-state info banner at the top:
//   - Active                  : no banner.
//   - Deleted (visible)       : yellow "Pipeline deleted on YYYY-MM-DD."
//   - Metadata not available  : NEUTRAL grey banner (not alarming) — the
//                               expected state for Vector Search / cross-region
//                               (plan §3.5). Cost stays accurate; config
//                               analysis is degraded.
//
// `created_by` / `run_as` are human-readable values straight from the system
// table — no GUID resolution, no REST API (plan §3.4, the key simplification
// over the Instance Pools modal).

import {
  AlertTriangle,
  Brain,
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
} from '@/lib/pipeline-display';

interface PipelineDetailsModalProps {
  pipelineId: string;
  // Disambiguates a pipeline_id that spans >1 workspace (plan §3.3/§6).
  workspaceId?: string;
  isOpen: boolean;
  onClose: () => void;
}

const formatDeleteDate = (dateStr?: string | null): string | null => {
  if (!dateStr) return null;
  try {
    return new Date(dateStr).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
    });
  } catch {
    return dateStr;
  }
};

export const PipelineDetailsModal = ({
  pipelineId,
  workspaceId,
  isOpen,
  onClose,
}: PipelineDetailsModalProps) => {
  const {
    data: details,
    isLoading: detailsLoading,
    error: detailsError,
  } = usePipelineDetails(pipelineId, workspaceId);
  const {
    data: analysis,
    isLoading: analysisLoading,
    error: analysisError,
  } = usePipelineAnalysis(pipelineId, workspaceId);

  const deletedDateLabel = formatDeleteDate(details?.pipeline_deleted_at);
  const caveat = costBasisCaveat(details?.cost_basis);

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="max-w-5xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="text-xl font-semibold flex items-center gap-2">
            <Workflow className="h-5 w-5" />
            Pipeline Configuration & Analysis
          </DialogTitle>
        </DialogHeader>

        {detailsError ? (
          <div className="text-center py-8">
            <div className="text-red-600 font-medium mb-2">
              Error loading pipeline details
            </div>
            <div className="text-sm text-muted-foreground">
              {detailsError.message}
            </div>
          </div>
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
                    Configuration shown is as of the delete time. Cost figures
                    remain accurate.
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
                    retention edges. Cost figures remain accurate; the
                    configuration below is unavailable.
                  </div>
                </div>
              </div>
            )}

            {/* Cost-basis caveat banner — only when the $ excludes cloud VM
                cost (classic / mixed — plan §3.2). */}
            {caveat && (
              <div className="flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-500/40 dark:bg-amber-500/10 dark:text-amber-200">
                <Info className="h-4 w-4 mt-0.5 shrink-0" />
                <div>
                  <div className="font-semibold">{caveat}.</div>
                  <div className="text-xs mt-1 opacity-90">
                    v1 surfaces Databricks DBU cost only. Cloud VM cost for
                    classic pipelines is a v2 follow-up.
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
                        Powered by Claude Sonnet 4
                      </Badge>
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
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
                        <div className="prose prose-sm max-w-none">
                          <div
                            className="text-sm leading-relaxed whitespace-pre-line"
                            // Same lightweight markdown massage as the other
                            // analysis modals so the surfaces feel consistent
                            // without adding a markdown renderer dependency.
                            dangerouslySetInnerHTML={{
                              __html: analysis.analysis
                                .replace(
                                  /\*\*(.*?)\*\*/g,
                                  '<strong>$1</strong>',
                                )
                                .replace(
                                  /### (.*?)$/gm,
                                  '<h3 class="font-semibold text-base mb-2 mt-4">$1</h3>',
                                )
                                .replace(
                                  /## (.*?)$/gm,
                                  '<h2 class="font-bold text-lg mb-3 mt-4">$1</h2>',
                                ),
                            }}
                          />
                        </div>
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
