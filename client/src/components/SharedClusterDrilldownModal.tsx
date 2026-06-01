import {
  PieChart,
  Pie,
  Cell,
  ResponsiveContainer,
  Tooltip,
  Legend,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
} from "recharts";
import {
  Server,
  DollarSign,
  Calendar,
  Brain,
  Lightbulb,
  TrendingUp,
} from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  useClusterDailyTrend,
  useClusterSpendBreakdown,
} from "@/hooks/useSharedClusters";
import { useClusterDetails, useClusterAnalysis } from "@/hooks/useJobSpends";
import { useCloudPlatform } from "@/contexts/CloudPlatformContext";
import type { DateRange, SharedClusterSpend } from "@/types/job-spend";

interface SharedClusterDrilldownModalProps {
  cluster: SharedClusterSpend | null;
  dateRange: DateRange;
  isOpen: boolean;
  onClose: () => void;
}

const formatCurrency = (amount: number) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount);

const formatDate = (dateStr?: string | null) => {
  if (!dateStr) return "N/A";
  try {
    return new Date(dateStr).toLocaleDateString("en-US", {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return dateStr;
  }
};

const formatTrendDate = (dateStr: string) => {
  try {
    return new Date(dateStr).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
    });
  } catch {
    return dateStr;
  }
};

export const SharedClusterDrilldownModal = ({
  cluster,
  dateRange,
  isOpen,
  onClose,
}: SharedClusterDrilldownModalProps) => {
  const { config: cloudConfig } = useCloudPlatform();
  const clusterId = cluster?.cluster_id ?? null;

  const {
    data: breakdown,
    isLoading: breakdownLoading,
    error: breakdownError,
  } = useClusterSpendBreakdown(clusterId, dateRange);
  const { data: trend, isLoading: trendLoading } = useClusterDailyTrend(
    clusterId,
    dateRange,
  );
  const { data: clusterDetails, isLoading: detailsLoading } = useClusterDetails(
    clusterId ?? "",
  );
  const {
    data: analysis,
    isLoading: analysisLoading,
    error: analysisError,
  } = useClusterAnalysis(clusterId ?? "");

  const trendPoints = trend?.data ?? [];

  const CustomPieTooltip = ({ active, payload }: any) => {
    if (active && payload && payload.length && breakdown) {
      const data = payload[0];
      const pct =
        breakdown.total_cost > 0
          ? ((data.value / breakdown.total_cost) * 100).toFixed(1)
          : "0.0";
      return (
        <div className="bg-popover text-popover-foreground p-3 border rounded-lg shadow-lg">
          <p className="font-medium">{data.payload.name}</p>
          <p className="text-blue-600 dark:text-blue-400">
            {formatCurrency(data.value)}
          </p>
          <p className="text-sm text-muted-foreground">{pct}% of total</p>
        </div>
      );
    }
    return null;
  };

  const TrendTooltip = ({ active, payload, label }: any) => {
    if (active && payload && payload.length) {
      const cloudCost =
        payload.find((p: any) => p.dataKey === "cloud_cost")?.value ?? 0;
      const dbuCost =
        payload.find((p: any) => p.dataKey === "databricks_cost")?.value ?? 0;
      return (
        <div className="bg-popover text-popover-foreground p-3 border rounded-lg shadow-lg space-y-1">
          <p className="font-medium">{formatTrendDate(label)}</p>
          <p className="text-blue-600 text-sm">
            Cloud: {formatCurrency(cloudCost)}
          </p>
          <p className="text-red-600 text-sm">DBU: {formatCurrency(dbuCost)}</p>
          <p className="font-semibold text-sm border-t pt-1">
            Total: {formatCurrency(cloudCost + dbuCost)}
          </p>
        </div>
      );
    }
    return null;
  };

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="max-w-5xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="text-xl font-semibold flex items-center gap-2">
            <Server className="h-5 w-5" />
            {cluster?.cluster_name || cluster?.cluster_id || "Shared Cluster"}
          </DialogTitle>
          {cluster?.cluster_name && (
            <p className="text-sm text-muted-foreground font-mono">
              {cluster.cluster_id}
            </p>
          )}
        </DialogHeader>

        {!cluster ? (
          <div className="text-center py-8 text-muted-foreground">
            No cluster selected
          </div>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 py-6">
            {/* Cost split pie */}
            <div className="space-y-4">
              <h3 className="text-lg font-semibold flex items-center">
                <DollarSign className="mr-2 h-5 w-5" />
                Cost Distribution
              </h3>

              {breakdownError ? (
                <div className="text-sm text-muted-foreground p-4 border rounded-lg">
                  No detailed breakdown available for this window.
                </div>
              ) : breakdownLoading ? (
                <Skeleton className="h-64 w-full rounded-lg" />
              ) : breakdown ? (
                <>
                  <div className="h-64">
                    <ResponsiveContainer width="100%" height="100%">
                      <PieChart>
                        <Pie
                          data={breakdown.cost_split}
                          cx="50%"
                          cy="50%"
                          labelLine={false}
                          label={({ name, percent }: any) =>
                            `${name ?? ""} (${((percent ?? 0) * 100).toFixed(1)}%)`
                          }
                          outerRadius={80}
                          dataKey="value"
                        >
                          {breakdown.cost_split.map((entry, idx) => (
                            <Cell key={`cell-${idx}`} fill={entry.color} />
                          ))}
                        </Pie>
                        <Tooltip content={<CustomPieTooltip />} />
                        <Legend />
                      </PieChart>
                    </ResponsiveContainer>
                  </div>
                  <div className="space-y-2">
                    {breakdown.cost_split.map((item) => (
                      <div
                        key={item.name}
                        className="flex items-center justify-between p-2 bg-muted/50 rounded"
                      >
                        <div className="flex items-center space-x-2">
                          <div
                            className="w-3 h-3 rounded-full"
                            style={{ backgroundColor: item.color }}
                          />
                          <span className="font-medium">{item.name}</span>
                        </div>
                        <span className="font-bold">
                          {formatCurrency(item.value)}
                        </span>
                      </div>
                    ))}
                    <div className="flex items-center justify-between p-2 bg-muted rounded font-bold">
                      <span>Total Cost</span>
                      <span>{formatCurrency(breakdown.total_cost)}</span>
                    </div>
                  </div>
                </>
              ) : null}
            </div>

            {/* Daily trend line */}
            <div className="space-y-4">
              <h3 className="text-lg font-semibold flex items-center">
                <TrendingUp className="mr-2 h-5 w-5" />
                Daily Spend
              </h3>

              {trendLoading ? (
                <Skeleton className="h-64 w-full rounded-lg" />
              ) : trendPoints.length === 0 ? (
                <div className="text-sm text-muted-foreground p-4 border rounded-lg">
                  No daily data in the selected window.
                </div>
              ) : (
                <div className="h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={trendPoints}>
                      <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                      <XAxis
                        dataKey="usage_date"
                        tickFormatter={formatTrendDate}
                        fontSize={11}
                      />
                      <YAxis
                        tickFormatter={(v: number) => `$${v.toFixed(0)}`}
                        fontSize={11}
                      />
                      <Tooltip content={<TrendTooltip />} />
                      <Legend />
                      <Line
                        type="monotone"
                        dataKey="cloud_cost"
                        name={`${cloudConfig?.compute_service || "Cloud"}`}
                        stroke="#3b82f6"
                        strokeWidth={2}
                        dot={false}
                      />
                      <Line
                        type="monotone"
                        dataKey="databricks_cost"
                        name="Databricks (DBU)"
                        stroke="#ef4444"
                        strokeWidth={2}
                        dot={false}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              )}
            </div>

            {/* Cluster configuration card */}
            <div className="lg:col-span-2 space-y-4">
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center text-lg">
                    <Server className="mr-2 h-5 w-5" />
                    Cluster Configuration
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  {detailsLoading ? (
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                      {[...Array(8)].map((_, i) => (
                        <Skeleton key={i} className="h-14 w-full" />
                      ))}
                    </div>
                  ) : (
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                      <div>
                        <div className="text-muted-foreground text-xs mb-1">
                          Owner
                        </div>
                        <div className="font-medium">
                          {clusterDetails?.owned_by || cluster.owned_by || "—"}
                        </div>
                      </div>
                      <div>
                        <div className="text-muted-foreground text-xs mb-1">
                          DBR Version
                        </div>
                        <div className="font-medium font-mono text-xs">
                          {clusterDetails?.dbr_version || "—"}
                        </div>
                      </div>
                      <div>
                        <div className="text-muted-foreground text-xs mb-1">
                          Security Mode
                        </div>
                        <div className="font-medium">
                          {clusterDetails?.data_security_mode ||
                            cluster.data_security_mode ||
                            "—"}
                        </div>
                      </div>
                      <div>
                        <div className="text-muted-foreground text-xs mb-1">
                          Auto-termination
                        </div>
                        <div className="font-medium">
                          {clusterDetails?.auto_termination_minutes != null ? (
                            `${clusterDetails.auto_termination_minutes} min`
                          ) : (
                            <Badge variant="destructive" className="text-xs">
                              Disabled
                            </Badge>
                          )}
                        </div>
                      </div>
                      <div>
                        <div className="text-muted-foreground text-xs mb-1">
                          Driver
                        </div>
                        <div className="font-medium font-mono text-xs">
                          {clusterDetails?.driver_node_type || "—"}
                        </div>
                      </div>
                      <div>
                        <div className="text-muted-foreground text-xs mb-1">
                          Worker
                        </div>
                        <div className="font-medium font-mono text-xs">
                          {clusterDetails?.worker_node_type || "—"}
                        </div>
                      </div>
                      <div>
                        <div className="text-muted-foreground text-xs mb-1">
                          Workers
                        </div>
                        <div className="font-medium">
                          {clusterDetails?.min_autoscale_workers != null &&
                          clusterDetails?.max_autoscale_workers != null
                            ? `${clusterDetails.min_autoscale_workers}–${clusterDetails.max_autoscale_workers}`
                            : (clusterDetails?.worker_count ?? "—")}
                        </div>
                      </div>
                      <div>
                        <div className="text-muted-foreground text-xs mb-1 flex items-center gap-1">
                          <Calendar className="h-3 w-3" />
                          Active
                        </div>
                        <div className="font-medium text-xs">
                          {formatDate(cluster.first_active_date)} →{" "}
                          {formatDate(cluster.last_active_date)}
                        </div>
                      </div>
                    </div>
                  )}
                </CardContent>
              </Card>
            </div>

            {/* LLM analysis */}
            <div className="lg:col-span-2 space-y-4">
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center text-lg">
                    <Brain className="mr-2 h-5 w-5 text-purple-600" />
                    AI Cluster Analysis
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
                      <Skeleton className="h-4 w-48" />
                      <Skeleton className="h-24 w-full" />
                      <Skeleton className="h-4 w-56" />
                      <Skeleton className="h-20 w-full" />
                    </div>
                  ) : analysis ? (
                    <div className="space-y-4">
                      <div className="flex items-start space-x-2">
                        <Lightbulb className="h-4 w-4 text-amber-500 mt-1 flex-shrink-0" />
                        <div className="prose prose-sm max-w-none">
                          <div
                            className="text-sm leading-relaxed whitespace-pre-line"
                            dangerouslySetInnerHTML={{
                              __html: analysis.analysis
                                .replace(
                                  /\*\*(.*?)\*\*/g,
                                  "<strong>$1</strong>",
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
                      </div>
                      <div className="text-xs text-muted-foreground border-t pt-2">
                        Generated on{" "}
                        {new Date(analysis.timestamp).toLocaleDateString(
                          "en-US",
                          {
                            year: "numeric",
                            month: "long",
                            day: "numeric",
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
        )}
      </DialogContent>
    </Dialog>
  );
};

export default SharedClusterDrilldownModal;
