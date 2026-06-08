// Pool details modal — renders pool config + pool-tuned LLM analysis.
//
// Distinct from `ClusterDetailsModal` (used elsewhere in the app to render
// cluster-level config + analysis) because pools and clusters have
// different upstream sources (`system.compute.instance_pools` vs
// `system.compute.clusters`) and different LLM prompts (pool prompt
// includes the v1 cloud-cost caveat per plan §3.2 / §9 / CP7).
//
// Renders the §3.5 three-state info banner at the top of the modal:
//   - Active                : no banner.
//   - Deleted (visible)     : yellow "Pool deleted on YYYY-MM-DD."
//                             configuration is shown as of the delete time.
//   - Snapshot missing      : yellow "Pool metadata unavailable."
//                             cost stays accurate but configuration analysis
//                             is materially degraded.
//
// Creator info is rendered as "Creator ID: <GUID>" sourced from the
// per-request REST API enrichment (plan §3.4 / CP6 — the system table
// `tags` column excludes default tags, so the REST API's
// `default_tags['DatabricksInstancePoolCreatorId']` is the only source).
// Renders italicized "Unknown creator" when the GUID is null. GUID →
// email resolution is deferred to v2 (plan §13).
//
// See plan §4.1 / CP10 (`docs/plan_instance_pools_tab.md`).

import {
  AlertTriangle,
  Brain,
  Info,
  Layers,
  Lightbulb,
  Tag,
  User,
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
  useInstancePoolAnalysis,
  useInstancePoolDetails,
} from '@/hooks/useInstancePools';

interface InstancePoolDetailsModalProps {
  poolId: string;
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

export const InstancePoolDetailsModal = ({
  poolId,
  isOpen,
  onClose,
}: InstancePoolDetailsModalProps) => {
  const {
    data: details,
    isLoading: detailsLoading,
    error: detailsError,
  } = useInstancePoolDetails(poolId);
  const {
    data: analysis,
    isLoading: analysisLoading,
    error: analysisError,
  } = useInstancePoolAnalysis(poolId);

  const deletedDateLabel = formatDeleteDate(details?.pool_deleted_at);

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="max-w-5xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="text-xl font-semibold flex items-center gap-2">
            <Layers className="h-5 w-5" />
            Instance Pool Configuration & Analysis
          </DialogTitle>
        </DialogHeader>

        {detailsError ? (
          <div className="text-center py-8">
            <div className="text-red-600 font-medium mb-2">
              Error loading pool details
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
            {details.pool_deleted_at && (
              <div className="flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-500/40 dark:bg-amber-500/10 dark:text-amber-200">
                <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
                <div>
                  <div className="font-semibold">
                    Pool deleted on {deletedDateLabel}.
                  </div>
                  <div className="text-xs mt-1 opacity-90">
                    Configuration shown is as of the delete time. Cost figures
                    remain accurate.
                  </div>
                </div>
              </div>
            )}
            {details.pool_snapshot_missing && !details.pool_deleted_at && (
              <div className="flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-500/40 dark:bg-amber-500/10 dark:text-amber-200">
                <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
                <div>
                  <div className="font-semibold">
                    Pool metadata unavailable.
                  </div>
                  <div className="text-xs mt-1 opacity-90">
                    No row found in{' '}
                    <span className="font-mono">
                      system.compute.instance_pools
                    </span>{' '}
                    — typically deleted before retention or located in another
                    region. Cost figures remain accurate; configuration
                    analysis is materially degraded.
                  </div>
                </div>
              </div>
            )}

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              {/* Pool Configuration */}
              <div className="space-y-4">
                <h3 className="text-lg font-semibold flex items-center">
                  <Layers className="mr-2 h-5 w-5" />
                  Pool Configuration
                </h3>

                <div className="p-4 border rounded-lg space-y-3">
                  <div className="flex justify-between items-start">
                    <span className="text-sm font-medium text-muted-foreground">
                      Pool Name
                    </span>
                    <div className="text-right max-w-[260px]">
                      <div className="text-sm font-medium truncate" title={details.pool_name ?? undefined}>
                        {details.pool_name ?? (
                          <span className="font-mono text-muted-foreground">
                            Pool {details.instance_pool_id}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="flex justify-between items-start">
                    <span className="text-sm font-medium text-muted-foreground">
                      Pool ID
                    </span>
                    <div className="text-right">
                      <div
                        className="font-mono text-xs max-w-[260px] truncate"
                        title={details.instance_pool_id}
                      >
                        {details.instance_pool_id}
                      </div>
                    </div>
                  </div>

                  <div className="flex justify-between items-start">
                    <span className="text-sm font-medium text-muted-foreground flex items-center gap-1">
                      <User className="h-3.5 w-3.5" />
                      Creator
                    </span>
                    <div className="text-right max-w-[260px]">
                      {details.pool_creator_id ? (
                        <div className="text-xs">
                          <div className="text-muted-foreground">
                            Creator ID
                          </div>
                          <div
                            className="font-mono truncate"
                            title="Databricks-internal user GUID. Resolving to email is a v2 follow-up (see README)."
                          >
                            {details.pool_creator_id}
                          </div>
                        </div>
                      ) : (
                        <div
                          className="text-sm italic text-muted-foreground"
                          title="No DatabricksInstancePoolCreatorId tag found on the REST API response (e.g. workspace-system-created pool, or REST API call failed)."
                        >
                          Unknown creator
                        </div>
                      )}
                    </div>
                  </div>
                </div>

                <div className="p-4 border rounded-lg space-y-3">
                  <h4 className="font-semibold">Node & Capacity</h4>

                  <div className="flex justify-between items-start">
                    <span className="text-sm font-medium text-muted-foreground">
                      Node Type
                    </span>
                    <div className="text-right">
                      <div className="text-sm font-mono">
                        {details.node_type ?? 'N/A'}
                      </div>
                    </div>
                  </div>

                  <div className="flex justify-between items-start">
                    <span className="text-sm font-medium text-muted-foreground">
                      Min Idle Instances
                    </span>
                    <div className="text-right">
                      <div className="text-sm">
                        {details.min_idle_instances ?? 'N/A'}
                      </div>
                    </div>
                  </div>

                  <div className="flex justify-between items-start">
                    <span className="text-sm font-medium text-muted-foreground">
                      Max Capacity
                    </span>
                    <div className="text-right">
                      <div className="text-sm">
                        {details.max_capacity ?? 'Unbounded'}
                      </div>
                    </div>
                  </div>

                  <div className="flex justify-between items-start">
                    <span className="text-sm font-medium text-muted-foreground">
                      Idle Auto-termination
                    </span>
                    <div className="text-right">
                      <div className="text-sm">
                        {details.idle_instance_autotermination_minutes != null
                          ? `${details.idle_instance_autotermination_minutes} minutes`
                          : 'N/A'}
                      </div>
                    </div>
                  </div>

                  <div className="flex justify-between items-start">
                    <span className="text-sm font-medium text-muted-foreground">
                      Preloaded Spark
                    </span>
                    <div className="text-right max-w-[200px]">
                      <Badge variant="secondary" className="text-xs">
                        {details.preloaded_spark_version || 'N/A'}
                      </Badge>
                    </div>
                  </div>
                </div>

                {details.custom_tags &&
                  Object.keys(details.custom_tags).length > 0 && (
                    <div className="p-4 border rounded-lg space-y-3">
                      <h4 className="font-semibold flex items-center gap-1">
                        <Tag className="h-4 w-4" /> Custom Tags
                      </h4>
                      <div className="flex flex-wrap gap-2">
                        {Object.entries(details.custom_tags).map(([k, v]) => (
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
                      <p className="text-xs text-muted-foreground flex items-start gap-1">
                        <Info className="h-3 w-3 mt-0.5 shrink-0" />
                        Default Databricks tags (including the auto-applied
                        creator tag) are not shown here — the system table
                        column excludes them.
                      </p>
                    </div>
                  )}
              </div>

              {/* AI Pool Analysis */}
              <div className="space-y-4">
                <Card>
                  <CardHeader>
                    <CardTitle className="flex items-center text-lg">
                      <Brain className="mr-2 h-5 w-5 text-purple-600" />
                      AI Pool Analysis
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
                        <div className="flex items-start space-x-2">
                          <Lightbulb className="h-4 w-4 text-amber-500 mt-1 flex-shrink-0" />
                          <div className="prose prose-sm max-w-none">
                            <div
                              className="text-sm leading-relaxed whitespace-pre-line"
                              // Same lightweight markdown massage as
                              // `ClusterDetailsModal` / `JobBreakdownModal`
                              // so the three analysis surfaces feel
                              // consistent and we don't add a markdown
                              // renderer dependency for one panel.
                              dangerouslySetInnerHTML={{
                                __html: analysis.analysis
                                  .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
                                  .replace(
                                    /### (.*?)$/gm,
                                    '<h3 class="font-semibold text-base mb-2 mt-4">$1</h3>',
                                  )
                                  .replace(
                                    /## (.*?)$/gm,
                                    '<h2 class="font-bold text-lg mb-3 mt-4">$1</h2>',
                                  )
                                  .replace(/• /g, '• '),
                              }}
                            />
                          </div>
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
            <div className="text-muted-foreground">No pool details available</div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
};
