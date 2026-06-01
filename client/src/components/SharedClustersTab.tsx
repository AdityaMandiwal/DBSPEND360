import { useState, useEffect, useRef } from "react";
import { Server, DollarSign, Users, AlertTriangle, Search } from "lucide-react";
import { format } from "date-fns";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { useDashboard } from "./DashboardContext";
import { useDatePresets } from "@/hooks/useJobSpends";
import { useSharedClusterSummary } from "@/hooks/useSharedClusters";
import { SharedClusterTable } from "./SharedClusterTable";
import { SharedClusterDrilldownModal } from "./SharedClusterDrilldownModal";
import type { SharedClusterSpend } from "@/types/job-spend";

const formatCurrency = (amount: number) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount);

const formatNumber = (n: number) => new Intl.NumberFormat("en-US").format(n);

const formatDisplayDate = (dateStr: string) => {
  try {
    return format(new Date(dateStr), "MMM dd, yyyy");
  } catch {
    return dateStr;
  }
};

const SummarySection = () => {
  const { dateRange } = useDashboard();
  const { data: summary, isLoading } = useSharedClusterSummary(dateRange);

  if (isLoading) {
    return (
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
  }

  if (!summary) {
    return null;
  }

  const dailyAvg = summary.total_spend / Math.max(summary.date_range_days, 1);
  const cloudPct =
    summary.total_spend > 0
      ? (summary.total_cloud_cost / summary.total_spend) * 100
      : 0;
  const dbuPct =
    summary.total_spend > 0
      ? (summary.total_databricks_cost / summary.total_spend) * 100
      : 0;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">
              Shared Cluster Spend
            </CardTitle>
            <DollarSign className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-blue-600">
              {formatCurrency(summary.total_spend)}
            </div>
            <p className="text-xs text-muted-foreground mt-1">
              {summary.date_range_days} day
              {summary.date_range_days !== 1 ? "s" : ""} period
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
              {formatNumber(summary.total_clusters)}
            </div>
            <p className="text-xs text-muted-foreground mt-1">
              {formatCurrency(dailyAvg)}/day avg
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Top Owner</CardTitle>
            <Users className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div
              className="text-lg font-bold text-purple-600 truncate"
              title={summary.top_owner?.owned_by ?? "—"}
            >
              {summary.top_owner?.owned_by ?? "—"}
            </div>
            <p className="text-xs text-muted-foreground mt-1">
              {summary.top_owner
                ? `${formatCurrency(summary.top_owner.total_cost)} across ${summary.top_owner.cluster_count} cluster${summary.top_owner.cluster_count === 1 ? "" : "s"}`
                : "No owner data"}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">
              Idle-Risk Clusters
            </CardTitle>
            <AlertTriangle className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-red-600">
              {formatNumber(summary.no_auto_termination_count)}
            </div>
            <p className="text-xs text-muted-foreground mt-1">
              {summary.no_auto_termination_pct.toFixed(1)}% of spend (
              {formatCurrency(summary.no_auto_termination_spend)}) on clusters
              with no auto-termination
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Owner top-N + cloud/dbu split */}
      {summary.total_spend > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <Card>
            <CardHeader>
              <CardTitle className="text-lg">Cost Split</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center space-x-2">
                    <div className="w-3 h-3 bg-blue-500 rounded-full" />
                    <span className="text-sm font-medium">Cloud Costs</span>
                  </div>
                  <div className="text-right">
                    <div className="font-semibold">
                      {formatCurrency(summary.total_cloud_cost)}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      {cloudPct.toFixed(1)}%
                    </div>
                  </div>
                </div>
                <div className="flex items-center justify-between">
                  <div className="flex items-center space-x-2">
                    <div className="w-3 h-3 bg-red-500 rounded-full" />
                    <span className="text-sm font-medium">
                      Databricks (DBU)
                    </span>
                  </div>
                  <div className="text-right">
                    <div className="font-semibold">
                      {formatCurrency(summary.total_databricks_cost)}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      {dbuPct.toFixed(1)}%
                    </div>
                  </div>
                </div>
                <div className="w-full bg-muted rounded-full h-2 mt-3 flex overflow-hidden">
                  <div
                    className="bg-blue-500 h-2"
                    style={{ width: `${cloudPct}%` }}
                  />
                  <div
                    className="bg-red-500 h-2"
                    style={{ width: `${dbuPct}%` }}
                  />
                </div>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-lg">Top Owners by Spend</CardTitle>
            </CardHeader>
            <CardContent>
              {summary.top_owners.length === 0 ? (
                <div className="text-center text-muted-foreground py-4">
                  No owner data for this period
                </div>
              ) : (
                <div className="space-y-3">
                  {summary.top_owners.map((owner, idx) => (
                    <div
                      key={`${owner.owned_by ?? "unknown"}-${idx}`}
                      className="flex justify-between items-center"
                    >
                      <div className="flex items-center space-x-2 min-w-0">
                        <span className="text-xs bg-muted text-muted-foreground px-2 py-1 rounded">
                          #{idx + 1}
                        </span>
                        <span
                          className="text-sm font-medium truncate"
                          title={owner.owned_by ?? "—"}
                        >
                          {owner.owned_by ?? "—"}
                        </span>
                        <Badge variant="outline" className="text-xs">
                          {owner.cluster_count} cluster
                          {owner.cluster_count === 1 ? "" : "s"}
                        </Badge>
                      </div>
                      <div className="text-sm font-semibold ml-2">
                        {formatCurrency(owner.total_cost)}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
};

const SharedClusterFilters = ({
  ownerFilter,
  onOwnerFilterChange,
  searchFilter,
  onSearchFilterChange,
}: {
  ownerFilter: string;
  onOwnerFilterChange: (value: string) => void;
  searchFilter: string;
  onSearchFilterChange: (value: string) => void;
}) => {
  const { dateRange, setDateRange } = useDashboard();
  const { data: presets } = useDatePresets();

  const [localOwner, setLocalOwner] = useState(ownerFilter);
  const [localSearch, setLocalSearch] = useState(searchFilter);
  const ownerDebounce = useRef<ReturnType<typeof setTimeout> | null>(null);
  const searchDebounce = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => setLocalOwner(ownerFilter), [ownerFilter]);
  useEffect(() => setLocalSearch(searchFilter), [searchFilter]);

  useEffect(
    () => () => {
      if (ownerDebounce.current) clearTimeout(ownerDebounce.current);
      if (searchDebounce.current) clearTimeout(searchDebounce.current);
    },
    [],
  );

  const handleOwnerChange = (v: string) => {
    setLocalOwner(v);
    if (ownerDebounce.current) clearTimeout(ownerDebounce.current);
    ownerDebounce.current = setTimeout(() => onOwnerFilterChange(v), 300);
  };

  const handleSearchChange = (v: string) => {
    setLocalSearch(v);
    if (searchDebounce.current) clearTimeout(searchDebounce.current);
    searchDebounce.current = setTimeout(() => onSearchFilterChange(v), 300);
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <div className="space-y-4">
        <Label className="text-sm font-semibold">Date Range</Label>
        {presets && (
          <div className="flex flex-wrap gap-2">
            {Object.entries(presets).map(([key, preset]) => (
              <Button
                key={key}
                variant="outline"
                size="sm"
                onClick={() =>
                  setDateRange({
                    start_date: preset.start_date,
                    end_date: preset.end_date,
                  })
                }
                className={cn(
                  "text-xs",
                  dateRange.start_date === preset.start_date &&
                    dateRange.end_date === preset.end_date &&
                    "bg-blue-50 border-blue-200 text-blue-700 dark:bg-blue-500/15 dark:border-blue-500/40 dark:text-blue-300",
                )}
              >
                {preset.label}
              </Button>
            ))}
          </div>
        )}
        <div className="grid grid-cols-2 gap-2">
          <div>
            <Label htmlFor="cluster-start" className="text-sm font-medium">
              Start Date
            </Label>
            <Input
              id="cluster-start"
              type="date"
              value={dateRange.start_date}
              onChange={(e) =>
                setDateRange({
                  start_date: e.target.value,
                  end_date: dateRange.end_date,
                })
              }
              className="mt-1"
            />
          </div>
          <div>
            <Label htmlFor="cluster-end" className="text-sm font-medium">
              End Date
            </Label>
            <Input
              id="cluster-end"
              type="date"
              value={dateRange.end_date}
              onChange={(e) =>
                setDateRange({
                  start_date: dateRange.start_date,
                  end_date: e.target.value,
                })
              }
              className="mt-1"
            />
          </div>
        </div>
      </div>

      <div className="space-y-4">
        <Label className="text-sm font-semibold">Filters</Label>
        <div className="grid grid-cols-1 gap-3">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Search by cluster name or ID..."
              value={localSearch}
              onChange={(e) => handleSearchChange(e.target.value)}
              className="pl-10"
            />
          </div>
          <div className="relative">
            <Users className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Filter by owner email..."
              value={localOwner}
              onChange={(e) => handleOwnerChange(e.target.value)}
              className="pl-10"
            />
          </div>
        </div>

        <div className="text-xs text-muted-foreground space-y-1">
          <div>
            <strong>Window:</strong> {formatDisplayDate(dateRange.start_date)} —{" "}
            {formatDisplayDate(dateRange.end_date)}
          </div>
          {(ownerFilter || searchFilter) && (
            <div>
              <strong>Active filters:</strong>{" "}
              {[
                searchFilter && `search="${searchFilter}"`,
                ownerFilter && `owner="${ownerFilter}"`,
              ]
                .filter(Boolean)
                .join(", ")}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export const SharedClustersTab = () => {
  const { dateRange } = useDashboard();
  const [ownerFilter, setOwnerFilter] = useState("");
  const [searchFilter, setSearchFilter] = useState("");
  const [selectedCluster, setSelectedCluster] =
    useState<SharedClusterSpend | null>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);

  const handleRowClick = (cluster: SharedClusterSpend) => {
    setSelectedCluster(cluster);
    setIsModalOpen(true);
  };

  const handleClose = () => {
    setIsModalOpen(false);
    setSelectedCluster(null);
  };

  return (
    <div className="space-y-6">
      <SummarySection />

      <Card>
        <CardHeader>
          <CardTitle>Filters & Controls</CardTitle>
        </CardHeader>
        <CardContent>
          <SharedClusterFilters
            ownerFilter={ownerFilter}
            onOwnerFilterChange={setOwnerFilter}
            searchFilter={searchFilter}
            onSearchFilterChange={setSearchFilter}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Shared Clusters</CardTitle>
          <p className="text-sm text-muted-foreground">
            All-Purpose / interactive clusters with non-zero spend in the
            selected window. Click a row for cost breakdown, daily trend, and AI
            configuration analysis.
          </p>
        </CardHeader>
        <CardContent>
          <SharedClusterTable
            dateRange={dateRange}
            ownerFilter={ownerFilter}
            searchFilter={searchFilter}
            onRowClick={handleRowClick}
          />
        </CardContent>
      </Card>

      <SharedClusterDrilldownModal
        cluster={selectedCluster}
        dateRange={dateRange}
        isOpen={isModalOpen}
        onClose={handleClose}
      />
    </div>
  );
};

export default SharedClustersTab;
