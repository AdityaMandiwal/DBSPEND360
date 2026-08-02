import { useState } from 'react';
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from 'recharts';
import { Calendar, Server, DollarSign, Brain, Lightbulb, Info, Search } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useJobBreakdown, useJobCostAnalysis, useClusterDetails, useClusterAnalysis, useAiModelLabel } from '@/hooks/useJobSpends';
import { useCloudPlatform } from '@/contexts/CloudPlatformContext';
import { useIsAws, useIsSegmentedPlatform, AWS_CLOUD_LABEL } from '@/hooks/useCloudGate';
import { closeOnly, HIGH_COST_USD } from '@/lib/utils';
import { OtherCostBreakdownModal } from './OtherCostBreakdownModal';
import { AnalysisMarkdown } from './AnalysisMarkdown';

interface JobBreakdownModalProps {
  jobId: string;
  runId: string;
  isOpen: boolean;
  onClose: () => void;
}

interface ClusterDetailsModalProps {
  clusterId: string;
  isOpen: boolean;
  onClose: () => void;
  // Routes the LLM cost-context half of the analysis to the matching
  // rollup table. Pass 'job' or 'all_purpose' from a tab that knows the
  // cluster's source. Leave undefined from the Instance Pools drill-down
  // — the backend probes `system.compute.clusters.cluster_source` to
  // pick the right rollup, so the modal works for both job-cluster and
  // all-purpose attachments without the caller knowing which (plan §6
  // / CP10 review #2).
  clusterKind?: 'job' | 'all_purpose';
}

export const JobBreakdownModal = ({ jobId, runId, isOpen, onClose }: JobBreakdownModalProps) => {
  const { config: cloudConfig } = useCloudPlatform();
  const aiModelLabel = useAiModelLabel();
  const isAws = useIsAws();
  const isSegmentedPlatform = useIsSegmentedPlatform();
  const { data: breakdown, isLoading, error } = useJobBreakdown(jobId, runId);
  const { data: analysis, isLoading: analysisLoading, error: analysisError } = useJobCostAnalysis(jobId, runId);
  const [isClusterDetailsOpen, setIsClusterDetailsOpen] = useState(false);
  const [isOtherBreakdownOpen, setIsOtherBreakdownOpen] = useState(false);

  // D12: the model's `cost_split` is data-shaped (`has_segmented = compute is not
  // None`) and is NOT trustworthy on AWS for runs straddling the deploy date.
  // Build a client-side 2-slice on AWS and feed it to every consumer of the split
  // (pie data, the <Cell> color map, and the legend/summary list).
  const awsCostSplit = breakdown
    ? [
        { name: AWS_CLOUD_LABEL, value: breakdown.cloud_cost, color: '#3b82f6' },
        { name: 'Databricks (DBU)', value: breakdown.databricks_cost, color: '#ef4444' },
      ]
    : [];
  // Drop zero-value slices (common on Azure when compute_cost lands as 0.0
  // while dollars sit in storage) so the chart/legend aren't visual clutter.
  const pieData = (isAws ? awsCostSplit : (breakdown?.cost_split ?? [])).filter(
    (entry) => (entry.value ?? 0) > 0,
  );
  // Positive allowlist (D14): segmented compute/storage/network is shown only for
  // Azure/GCP. AWS, Unknown, and the config-loading window all fall to the
  // always-correct cloud-vs-DBU 2-slice — never the data-shape branch.
  const hasSegmented = breakdown?.compute_cost != null;
  const showSegmented = hasSegmented && isSegmentedPlatform;
  const segmentPct = (value: number) =>
    breakdown && breakdown.total_cost > 0
      ? ((value / breakdown.total_cost) * 100).toFixed(1)
      : '0.0';
  const computeVal = breakdown?.compute_cost ?? 0;
  const storageVal = breakdown?.storage_cost ?? 0;
  const networkVal = breakdown?.network_cost ?? 0;
  const otherVal = breakdown?.other_cost ?? 0;

  const formatCurrency = (amount: number) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(amount);
  };

  const formatDate = (dateStr: string) => {
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

  const CustomTooltip = ({ active, payload }: any) => {
    if (active && payload && payload.length) {
      const data = payload[0];
      const percentage = ((data.value / breakdown!.total_cost) * 100).toFixed(1);
      return (
        <div className="bg-popover text-popover-foreground p-3 border rounded-lg shadow-lg">
          <p className="font-medium">{data.payload.name}</p>
          <p className="text-blue-600 dark:text-blue-400">{formatCurrency(data.value)}</p>
          <p className="text-sm text-muted-foreground">{percentage}% of total</p>
        </div>
      );
    }
    return null;
  };

  return (
    <Dialog open={isOpen} onOpenChange={closeOnly(onClose)}>
      <DialogContent className="max-w-4xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="text-xl font-semibold">
            Job Cost Breakdown
          </DialogTitle>
        </DialogHeader>

        {error ? (
          <div className="text-center py-8">
            <div className="text-red-600 font-medium mb-2">Error loading breakdown</div>
            <div className="text-sm text-muted-foreground">{error.message}</div>
          </div>
        ) : isLoading ? (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 py-6">
            {/* Loading skeleton for chart */}
            <div className="space-y-4">
              <Skeleton className="h-6 w-32" />
              <Skeleton className="h-64 w-full rounded-lg" />
            </div>
            {/* Loading skeleton for details */}
            <div className="space-y-4">
              <Skeleton className="h-6 w-32" />
              <div className="space-y-3">
                {[...Array(5)].map((_, i) => (
                  <div key={i} className="flex justify-between">
                    <Skeleton className="h-4 w-24" />
                    <Skeleton className="h-4 w-20" />
                  </div>
                ))}
              </div>
            </div>
          </div>
        ) : breakdown ? (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 py-6">
            {/* Cost Breakdown Chart */}
            <div className="space-y-4">
              <h3 className="text-lg font-semibold flex items-center">
                <DollarSign className="mr-2 h-5 w-5" />
                Cost Distribution
              </h3>

              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={pieData}
                      cx="50%"
                      cy="50%"
                      outerRadius={80}
                      fill="#8884d8"
                      dataKey="value"
                    >
                      {pieData.map((entry, index) => (
                        <Cell key={`cell-${index}`} fill={entry.color} />
                      ))}
                    </Pie>
                    <Tooltip content={<CustomTooltip />} />
                  </PieChart>
                </ResponsiveContainer>
              </div>

              {/* Cost Summary */}
              <div className="space-y-2">
                {pieData.map((item) => (
                  <div key={item.name} className="flex items-center justify-between p-2 bg-muted/50 rounded">
                    <div className="flex items-center space-x-2">
                      <div
                        className="w-3 h-3 rounded-full"
                        style={{ backgroundColor: item.color }}
                      ></div>
                      <span className="font-medium">{item.name}</span>
                    </div>
                    <div className="text-right">
                      <span className="font-bold">{formatCurrency(item.value)}</span>
                      <span className="text-xs text-muted-foreground ml-2">
                        ({breakdown.total_cost > 0 ? ((item.value / breakdown.total_cost) * 100).toFixed(1) : '0.0'}%)
                      </span>
                    </div>
                  </div>
                ))}
                <div className="flex items-center justify-between p-2 bg-muted rounded font-bold">
                  <span>Total Cost</span>
                  <span>{formatCurrency(breakdown.total_cost)}</span>
                </div>
              </div>
            </div>

            {/* Job Details */}
            <div className="space-y-4">
              <h3 className="text-lg font-semibold flex items-center">
                <Server className="mr-2 h-5 w-5" />
                Job Details
              </h3>

              <div className="space-y-4">
                {/* Job Information */}
                <div className="p-4 border rounded-lg space-y-3">
                  <div className="flex justify-between items-start">
                    <span className="text-sm font-medium text-muted-foreground">Job ID</span>
                    <div className="text-right">
                      <div className="font-mono text-sm max-w-[200px] truncate" title={breakdown.job_id}>
                        {breakdown.job_id}
                      </div>
                    </div>
                  </div>

                  <div className="flex justify-between items-start">
                    <span className="text-sm font-medium text-muted-foreground">Run ID</span>
                    <div className="text-right">
                      <div className="font-mono text-sm max-w-[200px] truncate" title={breakdown.run_id}>
                        {breakdown.run_id}
                      </div>
                    </div>
                  </div>

                  <div className="flex justify-between items-start">
                    <span className="text-sm font-medium text-muted-foreground">Cluster ID</span>
                    <div className="text-right flex items-center space-x-2">
                      <div className="font-mono text-sm max-w-[200px] truncate" title={breakdown.cluster_id}>
                        {breakdown.cluster_id}
                      </div>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-6 w-6 p-0"
                        onClick={() => setIsClusterDetailsOpen(true)}
                        title="View cluster details and AI analysis"
                      >
                        <Info className="h-3 w-3 text-blue-600" />
                      </Button>
                    </div>
                  </div>

                  <div className="flex justify-between items-center">
                    <span className="text-sm font-medium text-muted-foreground">
                      {breakdown.end_date ? 'Usage Period' : 'Usage Date'}
                    </span>
                    <div className="flex items-center text-sm">
                      <Calendar className="mr-1 h-4 w-4" />
                      {breakdown.end_date
                        ? `${formatDate(breakdown.usage_date)} — ${formatDate(breakdown.end_date)}`
                        : formatDate(breakdown.usage_date)}
                    </div>
                  </div>
                </div>

                {/* Cost Analysis */}
                <div className="p-4 border rounded-lg space-y-3">
                  <h4 className="font-semibold">Cost Analysis</h4>

                  {showSegmented ? (
                    <div className="grid grid-cols-2 gap-3">
                      {computeVal > 0 && (
                        <div className="text-center p-3 bg-blue-50 dark:bg-blue-500/10 rounded">
                          <div className="text-xl font-bold text-blue-600 dark:text-blue-400">
                            {segmentPct(computeVal)}%
                          </div>
                          <div className="text-xs text-blue-600 dark:text-blue-400">Compute</div>
                        </div>
                      )}
                      {storageVal > 0 && (
                        <div className="text-center p-3 bg-green-50 dark:bg-green-500/10 rounded">
                          <div className="text-xl font-bold text-green-600 dark:text-green-400">
                            {segmentPct(storageVal)}%
                          </div>
                          <div className="text-xs text-green-600 dark:text-green-400">Storage</div>
                        </div>
                      )}
                      {networkVal > 0 && (
                        <div className="text-center p-3 bg-amber-50 dark:bg-amber-500/10 rounded">
                          <div className="text-xl font-bold text-amber-600 dark:text-amber-400">
                            {segmentPct(networkVal)}%
                          </div>
                          <div className="text-xs text-amber-600 dark:text-amber-400">Network</div>
                        </div>
                      )}
                      {otherVal > 0 && (
                        <button
                          type="button"
                          className="text-center p-3 bg-muted/60 rounded cursor-pointer hover:bg-muted transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                          onClick={() => setIsOtherBreakdownOpen(true)}
                          title="Click to view breakdown of unclassified costs"
                          aria-label="View breakdown of unclassified costs"
                        >
                          <div className="text-xl font-bold text-muted-foreground">
                            {segmentPct(otherVal)}%
                          </div>
                          <div className="text-xs text-muted-foreground flex items-center justify-center gap-1">
                            Other <Search className="h-2.5 w-2.5" aria-hidden="true" />
                          </div>
                        </button>
                      )}
                      {breakdown.databricks_cost > 0 && (
                        <div className="text-center p-3 bg-red-50 dark:bg-red-500/10 rounded">
                          <div className="text-xl font-bold text-red-600 dark:text-red-400">
                            {segmentPct(breakdown.databricks_cost)}%
                          </div>
                          <div className="text-xs text-red-600 dark:text-red-400">DBU</div>
                        </div>
                      )}
                    </div>
                  ) : (
                    <div className="grid grid-cols-2 gap-4">
                      <div className="text-center p-3 bg-blue-50 dark:bg-blue-500/10 rounded">
                        <div className="text-2xl font-bold text-blue-600 dark:text-blue-400">
                          {breakdown.total_cost > 0 ? ((breakdown.cloud_cost / breakdown.total_cost) * 100).toFixed(1) : '0.0'}%
                        </div>
                        <div className="text-sm text-blue-600 dark:text-blue-400">{isAws ? AWS_CLOUD_LABEL : (cloudConfig?.compute_service || 'Cloud')} Share</div>
                      </div>
                      <div className="text-center p-3 bg-red-50 dark:bg-red-500/10 rounded">
                        <div className="text-2xl font-bold text-red-600 dark:text-red-400">
                          {breakdown.total_cost > 0 ? ((breakdown.databricks_cost / breakdown.total_cost) * 100).toFixed(1) : '0.0'}%
                        </div>
                        <div className="text-sm text-red-600 dark:text-red-400">Databricks Share</div>
                      </div>
                    </div>
                  )}

                  {/* Cost Indicators */}
                  <div className="space-y-2">
                    {breakdown.total_cost > HIGH_COST_USD && (
                      <Badge variant="destructive" className="w-full justify-center">
                        High Cost Job
                      </Badge>
                    )}
                    {breakdown.cloud_cost > breakdown.databricks_cost ? (
                      <Badge variant="secondary" className="w-full justify-center">
                        Cloud-Heavy Workload
                      </Badge>
                    ) : (
                      <Badge variant="secondary" className="w-full justify-center">
                        Databricks-Heavy Workload
                      </Badge>
                    )}
                  </div>
                </div>
              </div>
            </div>

            {/* AI Cost Analysis Section */}
            <div className="lg:col-span-2 space-y-4">
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center text-lg">
                    <Brain className="mr-2 h-5 w-5 text-purple-600" />
                    AI Cost Analysis
                    <Badge variant="secondary" className="ml-2 text-xs">
                      Powered by {aiModelLabel}
                    </Badge>
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  {analysisError ? (
                    <div className="text-center py-4">
                      <div className="text-red-600 font-medium mb-2">Analysis unavailable</div>
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
                      <Skeleton className="h-20 w-full" />
                      <div className="flex items-center space-x-2">
                        <Skeleton className="h-4 w-4 rounded-full" />
                        <Skeleton className="h-4 w-56" />
                      </div>
                      <Skeleton className="h-16 w-full" />
                    </div>
                  ) : analysis ? (
                    <div className="space-y-4">
                      <div className="flex items-start space-x-2">
                        <Lightbulb className="h-4 w-4 text-amber-500 mt-1 flex-shrink-0" />
                        <AnalysisMarkdown>{analysis.analysis}</AnalysisMarkdown>
                      </div>
                      <div className="text-xs text-muted-foreground border-t pt-2">
                        Generated on {new Date(analysis.timestamp).toLocaleDateString('en-US', {
                          year: 'numeric',
                          month: 'long',
                          day: 'numeric'
                        })}
                      </div>
                    </div>
                  ) : (
                    <div className="text-center py-4">
                      <div className="text-muted-foreground">No analysis available</div>
                    </div>
                  )}
                </CardContent>
              </Card>
            </div>
          </div>
        ) : (
          <div className="text-center py-8">
            <div className="text-muted-foreground">No breakdown data available</div>
          </div>
        )}

        {/* Cluster Details Modal */}
        {breakdown && (
          <>
            <ClusterDetailsModal
              clusterId={breakdown.cluster_id}
              isOpen={isClusterDetailsOpen}
              onClose={() => setIsClusterDetailsOpen(false)}
              clusterKind="job"
            />
            {!isAws && (
              <OtherCostBreakdownModal
                dateRange={{
                  start_date: breakdown.usage_date,
                  end_date: breakdown.end_date || breakdown.usage_date,
                }}
                clusterId={breakdown.cluster_id}
                isOpen={isOtherBreakdownOpen}
                onClose={() => setIsOtherBreakdownOpen(false)}
              />
            )}
          </>
        )}
      </DialogContent>
    </Dialog>
  );
};

export const ClusterDetailsModal = ({
  clusterId,
  isOpen,
  onClose,
  clusterKind,
}: ClusterDetailsModalProps) => {
  const { data: clusterDetails, isLoading: detailsLoading, error: detailsError } = useClusterDetails(clusterId);
  const { data: clusterAnalysis, isLoading: analysisLoading, error: analysisError } = useClusterAnalysis(clusterId, clusterKind);
  const aiModelLabel = useAiModelLabel();

  const formatDate = (dateStr?: string) => {
    if (!dateStr) return 'N/A';
    try {
      return new Date(dateStr).toLocaleDateString('en-US', {
        year: 'numeric',
        month: 'long',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      });
    } catch {
      return dateStr;
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={closeOnly(onClose)}>
      <DialogContent className="max-w-5xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="text-xl font-semibold">
            Cluster Configuration & Analysis
          </DialogTitle>
        </DialogHeader>

        {detailsError ? (
          <div className="text-center py-8">
            <div className="text-red-600 font-medium mb-2">Error loading cluster details</div>
            <div className="text-sm text-muted-foreground">{detailsError.message}</div>
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
        ) : clusterDetails ? (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 py-6">
            {/* Cluster Configuration */}
            <div className="space-y-4">
              <h3 className="text-lg font-semibold flex items-center">
                <Server className="mr-2 h-5 w-5" />
                Cluster Configuration
              </h3>

              <div className="space-y-4">
                <div className="p-4 border rounded-lg space-y-3">
                  <div className="flex justify-between items-start">
                    <span className="text-sm font-medium text-muted-foreground">Cluster ID</span>
                    <div className="text-right">
                      <div className="font-mono text-sm" title={clusterDetails.cluster_id}>
                        {clusterDetails.cluster_id}
                      </div>
                    </div>
                  </div>

                  <div className="flex justify-between items-start">
                    <span className="text-sm font-medium text-muted-foreground">Owner</span>
                    <div className="text-right">
                      <div className="text-sm">{clusterDetails.owned_by || 'N/A'}</div>
                    </div>
                  </div>

                  <div className="flex justify-between items-start">
                    <span className="text-sm font-medium text-muted-foreground">Created</span>
                    <div className="text-right">
                      <div className="text-sm">{formatDate(clusterDetails.create_time)}</div>
                    </div>
                  </div>

                  <div className="flex justify-between items-start">
                    <span className="text-sm font-medium text-muted-foreground">DBR Version</span>
                    <div className="text-right">
                      <Badge variant="secondary" className="text-xs">
                        {clusterDetails.dbr_version || 'N/A'}
                      </Badge>
                    </div>
                  </div>

                  <div className="flex justify-between items-start">
                    <span className="text-sm font-medium text-muted-foreground">Security Mode</span>
                    <div className="text-right">
                      <Badge variant="outline" className="text-xs">
                        {clusterDetails.data_security_mode || 'N/A'}
                      </Badge>
                    </div>
                  </div>
                </div>

                <div className="p-4 border rounded-lg space-y-3">
                  <h4 className="font-semibold">Node Configuration</h4>

                  <div className="flex justify-between items-start">
                    <span className="text-sm font-medium text-muted-foreground">Driver Node</span>
                    <div className="text-right">
                      <div className="text-sm font-mono">{clusterDetails.driver_node_type || 'N/A'}</div>
                    </div>
                  </div>

                  <div className="flex justify-between items-start">
                    <span className="text-sm font-medium text-muted-foreground">Worker Node</span>
                    <div className="text-right">
                      <div className="text-sm font-mono">{clusterDetails.worker_node_type || 'N/A'}</div>
                    </div>
                  </div>

                  <div className="flex justify-between items-start">
                    <span className="text-sm font-medium text-muted-foreground">Worker Count</span>
                    <div className="text-right">
                      <div className="text-sm">{clusterDetails.worker_count || 'N/A'}</div>
                    </div>
                  </div>

                  {(clusterDetails.min_autoscale_workers || clusterDetails.max_autoscale_workers) && (
                    <div className="flex justify-between items-start">
                      <span className="text-sm font-medium text-muted-foreground">Autoscaling</span>
                      <div className="text-right">
                        <div className="text-sm">
                          {clusterDetails.min_autoscale_workers} - {clusterDetails.max_autoscale_workers} workers
                        </div>
                      </div>
                    </div>
                  )}

                  <div className="flex justify-between items-start">
                    <span className="text-sm font-medium text-muted-foreground">Auto-termination</span>
                    <div className="text-right">
                      <div className="text-sm">
                        {clusterDetails.auto_termination_minutes
                          ? `${clusterDetails.auto_termination_minutes} minutes`
                          : clusterDetails.cluster_source?.toUpperCase() === 'JOB'
                            ? 'N/A (ephemeral)'
                            : 'Disabled'}
                      </div>
                    </div>
                  </div>

                  <div className="flex justify-between items-start">
                    <span className="text-sm font-medium text-muted-foreground">Elastic Disk</span>
                    <div className="text-right">
                      <Badge variant={clusterDetails.enable_elastic_disk ? "default" : "secondary"} className="text-xs">
                        {clusterDetails.enable_elastic_disk ? 'Enabled' : 'Disabled'}
                      </Badge>
                    </div>
                  </div>
                </div>

                {clusterDetails.aws_attributes && (
                  <div className="p-4 border rounded-lg space-y-3">
                    <h4 className="font-semibold">AWS Configuration</h4>

                    <div className="flex justify-between items-start">
                      <span className="text-sm font-medium text-muted-foreground">Availability</span>
                      <div className="text-right">
                        <Badge variant="outline" className="text-xs">
                          {clusterDetails.aws_attributes.availability || 'N/A'}
                        </Badge>
                      </div>
                    </div>

                    {clusterDetails.aws_attributes.spot_bid_price_percent != null && (
                      <div className="flex justify-between items-start">
                        <span className="text-sm font-medium text-muted-foreground">Spot Bid</span>
                        <div className="text-right">
                          <div className="text-sm">{clusterDetails.aws_attributes.spot_bid_price_percent}%</div>
                        </div>
                      </div>
                    )}

                    {clusterDetails.aws_attributes.zone_id && (
                      <div className="flex justify-between items-start">
                        <span className="text-sm font-medium text-muted-foreground">AZ</span>
                        <div className="text-right">
                          <div className="text-sm font-mono">{clusterDetails.aws_attributes.zone_id}</div>
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {clusterDetails.azure_attributes && (
                  <div className="p-4 border rounded-lg space-y-3">
                    <h4 className="font-semibold">Azure Configuration</h4>

                    <div className="flex justify-between items-start">
                      <span className="text-sm font-medium text-muted-foreground">Availability</span>
                      <div className="text-right">
                        <Badge variant="outline" className="text-xs">
                          {clusterDetails.azure_attributes.availability || 'N/A'}
                        </Badge>
                      </div>
                    </div>

                    {clusterDetails.azure_attributes.spot_bid_max_price != null && (
                      <div className="flex justify-between items-start">
                        <span className="text-sm font-medium text-muted-foreground">Spot Bid Max</span>
                        <div className="text-right">
                          <div className="text-sm">{clusterDetails.azure_attributes.spot_bid_max_price}</div>
                        </div>
                      </div>
                    )}

                    {clusterDetails.azure_attributes.first_on_demand != null && (
                      <div className="flex justify-between items-start">
                        <span className="text-sm font-medium text-muted-foreground">First On-Demand</span>
                        <div className="text-right">
                          <div className="text-sm">{clusterDetails.azure_attributes.first_on_demand}</div>
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {clusterDetails.gcp_attributes && (
                  <div className="p-4 border rounded-lg space-y-3">
                    <h4 className="font-semibold">GCP Configuration</h4>

                    <div className="flex justify-between items-start">
                      <span className="text-sm font-medium text-muted-foreground">Availability</span>
                      <div className="text-right">
                        <Badge variant="outline" className="text-xs">
                          {clusterDetails.gcp_attributes.availability || 'N/A'}
                        </Badge>
                      </div>
                    </div>

                    {clusterDetails.gcp_attributes.zone_id && (
                      <div className="flex justify-between items-start">
                        <span className="text-sm font-medium text-muted-foreground">Zone</span>
                        <div className="text-right">
                          <div className="text-sm font-mono">{clusterDetails.gcp_attributes.zone_id}</div>
                        </div>
                      </div>
                    )}

                    {clusterDetails.gcp_attributes.boot_disk_size != null && (
                      <div className="flex justify-between items-start">
                        <span className="text-sm font-medium text-muted-foreground">Boot Disk Size</span>
                        <div className="text-right">
                          <div className="text-sm">{clusterDetails.gcp_attributes.boot_disk_size} GB</div>
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>

            {/* AI Cluster Analysis */}
            <div className="space-y-4">
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center text-lg">
                    <Brain className="mr-2 h-5 w-5 text-purple-600" />
                    AI Cluster Analysis
                    <Badge variant="secondary" className="ml-2 text-xs">
                      Powered by {aiModelLabel}
                    </Badge>
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  {analysisError ? (
                    <div className="text-center py-4">
                      <div className="text-red-600 font-medium mb-2">Analysis unavailable</div>
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
                  ) : clusterAnalysis ? (
                    <div className="space-y-4">
                      <div className="flex items-start space-x-2">
                        <Lightbulb className="h-4 w-4 text-amber-500 mt-1 flex-shrink-0" />
                        <AnalysisMarkdown>{clusterAnalysis.analysis}</AnalysisMarkdown>
                      </div>
                      <div className="text-xs text-muted-foreground border-t pt-2">
                        Generated on {new Date(clusterAnalysis.timestamp).toLocaleDateString('en-US', {
                          year: 'numeric',
                          month: 'long',
                          day: 'numeric'
                        })}
                      </div>
                    </div>
                  ) : (
                    <div className="text-center py-4">
                      <div className="text-muted-foreground">No analysis available</div>
                    </div>
                  )}
                </CardContent>
              </Card>
            </div>
          </div>
        ) : (
          <div className="text-center py-8">
            <div className="text-muted-foreground">No cluster details available</div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
};