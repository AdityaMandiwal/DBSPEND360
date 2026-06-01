import { useState, useEffect, useRef } from "react";
import {
  Boxes,
  DollarSign,
  AlertTriangle,
  Search,
  TrendingDown,
  Ghost,
} from "lucide-react";
import { format } from "date-fns";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import { useDashboard } from "./DashboardContext";
import { useDatePresets } from "@/hooks/useJobSpends";
import { useInstancePoolsSummary } from "@/hooks/useInstancePools";
import { InstancePoolTable } from "./InstancePoolTable";
import { InstancePoolDrilldownModal } from "./InstancePoolDrilldownModal";
import type { InstancePoolSpend } from "@/types/job-spend";

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
  const { data: summary, isLoading } = useInstancePoolsSummary(dateRange);

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

  const dailyAvg =
    summary.idle_waste_total / Math.max(summary.date_range_days, 1);

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        {/* Headline KPI: idle waste */}
        <Card className="border-amber-200 dark:border-amber-500/40">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Idle VM Cost</CardTitle>
            <TrendingDown className="h-4 w-4 text-amber-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-amber-600">
              {formatCurrency(summary.idle_waste_total)}
            </div>
            <p className="text-xs text-muted-foreground mt-1">
              {summary.idle_waste_pct.toFixed(1)}% of pool spend ·{" "}
              {formatCurrency(dailyAvg)}/day avg
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Pool Spend</CardTitle>
            <DollarSign className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-blue-600">
              {formatCurrency(summary.total_spend)}
            </div>
            <p className="text-xs text-muted-foreground mt-1">
              {summary.date_range_days} day
              {summary.date_range_days !== 1 ? "s" : ""} ·{" "}
              {formatNumber(summary.total_pools)} pool
              {summary.total_pools === 1 ? "" : "s"}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">
              High-Idle Pools
            </CardTitle>
            <AlertTriangle className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-red-600">
              {formatNumber(summary.high_idle_pool_count)}
            </div>
            <p className="text-xs text-muted-foreground mt-1">
              Pools with idle share &gt; 30%
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Orphan Pools</CardTitle>
            <Ghost className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-red-600">
              {formatNumber(summary.orphan_pool_count)}
            </div>
            <p className="text-xs text-muted-foreground mt-1">
              No clusters attached · 100% waste
            </p>
          </CardContent>
        </Card>
      </div>

      {summary.total_spend > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Pool Cost Split</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center space-x-2">
                  <div className="w-3 h-3 bg-blue-500 rounded-full" />
                  <span className="text-sm font-medium">
                    Pool Cloud Cost (VMs)
                  </span>
                </div>
                <div className="text-right">
                  <div className="font-semibold">
                    {formatCurrency(summary.total_pool_cloud_cost)}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {summary.total_spend > 0
                      ? (
                          (summary.total_pool_cloud_cost /
                            summary.total_spend) *
                          100
                        ).toFixed(1)
                      : "0.0"}
                    %
                  </div>
                </div>
              </div>
              <div className="flex items-center justify-between">
                <div className="flex items-center space-x-2">
                  <div className="w-3 h-3 bg-red-500 rounded-full" />
                  <span className="text-sm font-medium">
                    Databricks (DBU surcharge)
                  </span>
                </div>
                <div className="text-right">
                  <div className="font-semibold">
                    {formatCurrency(summary.total_databricks_cost)}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {summary.total_spend > 0
                      ? (
                          (summary.total_databricks_cost /
                            summary.total_spend) *
                          100
                        ).toFixed(1)
                      : "0.0"}
                    %
                  </div>
                </div>
              </div>
              <div className="text-xs text-muted-foreground border-t pt-2">
                DBU surcharge is non-zero only on premium-edition pool surcharge
                SKUs. Cluster runtime DBU bills to the cluster, not the pool.
              </div>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
};

const InstancePoolFilters = ({
  searchFilter,
  onSearchFilterChange,
}: {
  searchFilter: string;
  onSearchFilterChange: (value: string) => void;
}) => {
  const { dateRange, setDateRange } = useDashboard();
  const { data: presets } = useDatePresets();

  const [localSearch, setLocalSearch] = useState(searchFilter);
  const searchDebounce = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => setLocalSearch(searchFilter), [searchFilter]);

  useEffect(
    () => () => {
      if (searchDebounce.current) clearTimeout(searchDebounce.current);
    },
    [],
  );

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
            <Label htmlFor="pool-start" className="text-sm font-medium">
              Start Date
            </Label>
            <Input
              id="pool-start"
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
            <Label htmlFor="pool-end" className="text-sm font-medium">
              End Date
            </Label>
            <Input
              id="pool-end"
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
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search by pool name or ID..."
            value={localSearch}
            onChange={(e) => handleSearchChange(e.target.value)}
            className="pl-10"
          />
        </div>

        <div className="text-xs text-muted-foreground space-y-1">
          <div>
            <strong>Window:</strong> {formatDisplayDate(dateRange.start_date)} —{" "}
            {formatDisplayDate(dateRange.end_date)}
          </div>
          {searchFilter && (
            <div>
              <strong>Active filter:</strong> search="{searchFilter}"
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export const InstancePoolsTab = () => {
  const { dateRange } = useDashboard();
  const [searchFilter, setSearchFilter] = useState("");
  const [selectedPool, setSelectedPool] = useState<InstancePoolSpend | null>(
    null,
  );
  const [isModalOpen, setIsModalOpen] = useState(false);

  const handleRowClick = (pool: InstancePoolSpend) => {
    setSelectedPool(pool);
    setIsModalOpen(true);
  };

  const handleClose = () => {
    setIsModalOpen(false);
    setSelectedPool(null);
  };

  return (
    <div className="space-y-6">
      <SummarySection />

      <Card>
        <CardHeader>
          <CardTitle>Filters & Controls</CardTitle>
        </CardHeader>
        <CardContent>
          <InstancePoolFilters
            searchFilter={searchFilter}
            onSearchFilterChange={setSearchFilter}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Boxes className="h-5 w-5 text-muted-foreground" />
            Instance Pools
          </CardTitle>
          <p className="text-sm text-muted-foreground">
            Sorted by idle VM cost — the pool VMs incurring spend with no
            cluster attached. Click a row for the daily idle vs active split,
            attached clusters, and AI configuration analysis.
          </p>
        </CardHeader>
        <CardContent>
          <InstancePoolTable
            dateRange={dateRange}
            searchFilter={searchFilter}
            onRowClick={handleRowClick}
          />
        </CardContent>
      </Card>

      <InstancePoolDrilldownModal
        pool={selectedPool}
        dateRange={dateRange}
        isOpen={isModalOpen}
        onClose={handleClose}
      />
    </div>
  );
};

export default InstancePoolsTab;
