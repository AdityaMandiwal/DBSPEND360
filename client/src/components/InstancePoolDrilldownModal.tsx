import {
  BarChart,
  Bar,
  ResponsiveContainer,
  Tooltip,
  Legend,
  XAxis,
  YAxis,
  CartesianGrid,
} from "recharts";
import {
  Boxes,
  DollarSign,
  Calendar,
  Brain,
  Lightbulb,
  TrendingDown,
  Server,
  AlertTriangle,
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
  useInstancePoolBreakdown,
  useInstancePoolAttachedClusters,
  useInstancePoolAnalysis,
} from "@/hooks/useInstancePools";
import type { DateRange, InstancePoolSpend } from "@/types/job-spend";

interface InstancePoolDrilldownModalProps {
  pool: InstancePoolSpend | null;
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

const formatIdleTimeout = (minutes?: number | null) => {
  if (minutes == null || minutes === 0) return "Disabled";
  return `${minutes} min`;
};

export const InstancePoolDrilldownModal = ({
  pool,
  dateRange,
  isOpen,
  onClose,
}: InstancePoolDrilldownModalProps) => {
  const poolId = pool?.instance_pool_id ?? null;

  const {
    data: breakdown,
    isLoading: breakdownLoading,
    error: breakdownError,
  } = useInstancePoolBreakdown(poolId, dateRange);
  const { data: attached, isLoading: attachedLoading } =
    useInstancePoolAttachedClusters(poolId);
  const {
    data: analysis,
    isLoading: analysisLoading,
    error: analysisError,
  } = useInstancePoolAnalysis(poolId);

  const dailyPoints = breakdown?.daily ?? [];
  const attachedClusters = attached?.data ?? [];

  const TrendTooltip = ({ active, payload, label }: any) => {
    if (active && payload && payload.length) {
      const idle =
        payload.find((p: any) => p.dataKey === "idle_cloud_cost")?.value ?? 0;
      const active_ =
        payload.find((p: any) => p.dataKey === "active_cloud_cost")?.value ?? 0;
      return (
        <div className="bg-popover text-popover-foreground p-3 border rounded-lg shadow-lg space-y-1">
          <p className="font-medium">{formatTrendDate(label)}</p>
          <p className="text-amber-600 text-sm">Idle: {formatCurrency(idle)}</p>
          <p className="text-blue-600 text-sm">
            Active: {formatCurrency(active_)}
          </p>
          <p className="font-semibold text-sm border-t pt-1">
            Pool Total: {formatCurrency(idle + active_)}
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
            <Boxes className="h-5 w-5" />
            {pool?.instance_pool_name ||
              pool?.instance_pool_id ||
              "Instance Pool"}
            {pool?.is_orphan && (
              <Badge variant="destructive" className="ml-2 text-xs">
                Orphan
              </Badge>
            )}
          </DialogTitle>
          {pool?.instance_pool_name && (
            <p className="text-sm text-muted-foreground font-mono">
              {pool.instance_pool_id}
            </p>
          )}
        </DialogHeader>

        {!pool ? (
          <div className="text-center py-8 text-muted-foreground">
            No pool selected
          </div>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 py-6">
            {/* Daily idle vs active stacked bar chart */}
            <div className="lg:col-span-2 space-y-4">
              <h3 className="text-lg font-semibold flex items-center">
                <DollarSign className="mr-2 h-5 w-5" />
                Daily Idle vs Active Cloud Cost
              </h3>

              {breakdownError ? (
                <div className="text-sm text-muted-foreground p-4 border rounded-lg">
                  No detailed breakdown available for this window.
                </div>
              ) : breakdownLoading ? (
                <Skeleton className="h-72 w-full rounded-lg" />
              ) : dailyPoints.length === 0 ? (
                <div className="text-sm text-muted-foreground p-4 border rounded-lg">
                  No daily data in the selected window.
                </div>
              ) : (
                <div className="h-72">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={dailyPoints}>
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
                      <Bar
                        dataKey="active_cloud_cost"
                        name="Active (attached)"
                        stackId="cost"
                        fill="#3b82f6"
                      />
                      <Bar
                        dataKey="idle_cloud_cost"
                        name="Idle (no attachment)"
                        stackId="cost"
                        fill="#f59e0b"
                      />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}
              {breakdown && (
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
                  <div className="p-3 bg-muted/50 rounded">
                    <div className="text-muted-foreground text-xs mb-1">
                      Pool Total
                    </div>
                    <div className="font-bold">
                      {formatCurrency(breakdown.pool_total_cost)}
                    </div>
                  </div>
                  <div className="p-3 bg-muted/50 rounded">
                    <div className="text-muted-foreground text-xs mb-1">
                      Active
                    </div>
                    <div className="font-bold text-blue-600">
                      {formatCurrency(breakdown.active_cloud_cost)}
                    </div>
                  </div>
                  <div className="p-3 bg-muted/50 rounded">
                    <div className="text-muted-foreground text-xs mb-1">
                      Idle Waste
                    </div>
                    <div className="font-bold text-amber-600">
                      {formatCurrency(breakdown.idle_cloud_cost)}
                    </div>
                  </div>
                  <div className="p-3 bg-muted/50 rounded">
                    <div className="text-muted-foreground text-xs mb-1">
                      DBU Surcharge
                    </div>
                    <div className="font-bold text-red-600">
                      {formatCurrency(breakdown.databricks_cost)}
                    </div>
                  </div>
                </div>
              )}
            </div>

            {/* Pool config card */}
            <div className="lg:col-span-2">
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center text-lg">
                    <Boxes className="mr-2 h-5 w-5" />
                    Pool Configuration
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                    <div>
                      <div className="text-muted-foreground text-xs mb-1">
                        Node Type
                      </div>
                      <div className="font-medium font-mono text-xs">
                        {pool.node_type_id || "—"}
                      </div>
                    </div>
                    <div>
                      <div className="text-muted-foreground text-xs mb-1">
                        State
                      </div>
                      <div className="font-medium">{pool.state || "—"}</div>
                    </div>
                    <div>
                      <div className="text-muted-foreground text-xs mb-1">
                        Min Idle Instances
                      </div>
                      <div className="font-medium">
                        {pool.min_idle_instances ?? "—"}
                      </div>
                    </div>
                    <div>
                      <div className="text-muted-foreground text-xs mb-1">
                        Max Capacity
                      </div>
                      <div className="font-medium">
                        {pool.max_capacity ?? "—"}
                      </div>
                    </div>
                    <div>
                      <div className="text-muted-foreground text-xs mb-1">
                        Idle Timeout
                      </div>
                      <div className="font-medium">
                        {formatIdleTimeout(
                          pool.idle_instance_autotermination_minutes,
                        )}
                        {pool.idle_instance_autotermination_minutes == null && (
                          <Badge variant="destructive" className="ml-2 text-xs">
                            Disabled
                          </Badge>
                        )}
                      </div>
                    </div>
                    <div>
                      <div className="text-muted-foreground text-xs mb-1">
                        Workspace
                      </div>
                      <div className="font-medium font-mono text-xs">
                        {pool.workspace_id || "—"}
                      </div>
                    </div>
                    <div>
                      <div className="text-muted-foreground text-xs mb-1 flex items-center gap-1">
                        <Calendar className="h-3 w-3" />
                        Active
                      </div>
                      <div className="font-medium text-xs">
                        {formatDate(pool.first_active_date)} →{" "}
                        {formatDate(pool.last_active_date)}
                      </div>
                    </div>
                    <div>
                      <div className="text-muted-foreground text-xs mb-1">
                        Currency
                      </div>
                      <div className="font-medium">
                        {pool.currency || "USD"}
                      </div>
                    </div>
                  </div>
                </CardContent>
              </Card>
            </div>

            {/* Attached clusters mini-table */}
            <div className="lg:col-span-2">
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center text-lg">
                    <Server className="mr-2 h-5 w-5" />
                    Attached Clusters
                    <Badge variant="secondary" className="ml-2 text-xs">
                      {attachedClusters.length}
                    </Badge>
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  {attachedLoading ? (
                    <div className="space-y-2">
                      {[...Array(3)].map((_, i) => (
                        <Skeleton key={i} className="h-10 w-full" />
                      ))}
                    </div>
                  ) : attachedClusters.length === 0 ? (
                    <div className="flex items-center gap-2 text-sm text-muted-foreground p-3 border border-dashed border-amber-300 dark:border-amber-500/40 rounded">
                      <AlertTriangle className="h-4 w-4 text-amber-500" />
                      No clusters currently attached. Every dollar of pool spend
                      in this window is idle waste.
                    </div>
                  ) : (
                    <div className="space-y-2">
                      {attachedClusters.map((cluster) => (
                        <div
                          key={cluster.cluster_id}
                          className="flex items-center justify-between p-2 bg-muted/40 rounded"
                        >
                          <div className="min-w-0 flex-1">
                            <div className="font-medium truncate">
                              {cluster.cluster_name || cluster.cluster_id}
                            </div>
                            <div className="text-xs text-muted-foreground font-mono truncate">
                              {cluster.cluster_id}
                            </div>
                          </div>
                          <div className="flex items-center gap-2 flex-shrink-0 ml-3">
                            {cluster.cluster_source && (
                              <Badge variant="outline" className="text-xs">
                                {cluster.cluster_source}
                              </Badge>
                            )}
                            {cluster.link && (
                              <Badge variant="secondary" className="text-xs">
                                {cluster.link}
                              </Badge>
                            )}
                            <span className="text-xs text-muted-foreground hidden md:inline">
                              {cluster.owned_by || "—"}
                            </span>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </CardContent>
              </Card>
            </div>

            {/* LLM analysis */}
            <div className="lg:col-span-2">
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
                      <div className="text-xs text-muted-foreground border-t pt-2 flex items-center gap-1">
                        <TrendingDown className="h-3 w-3" />
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

export default InstancePoolDrilldownModal;
