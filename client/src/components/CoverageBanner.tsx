import { Info } from "lucide-react";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  formatExampleWorkspaceNames,
  useCoverageSummary,
  type CoverageTabKey,
} from "@/hooks/useCoverage";
import type { DateRange } from "@/types/job-spend";

const currencyFormatter = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 0,
  maximumFractionDigits: 0,
});

interface CoverageBannerProps {
  tab: CoverageTabKey;
  dateRange?: DateRange;
}

// Second paragraph of the popover — describes how the current tab TREATS the
// non-covered workspaces. The SQL Warehouse tab differs from the other four
// in two material ways, so its copy is a separate branch:
//
//   1. The KPI totals actively EXCLUDE non-covered DBU (all other tabs
//      include the DBU and only miss the cloud/VM column).
//   2. Serverless DBU is complete, while Classic/Pro customer-cloud
//      infrastructure is not attributed by the warehouse rollup.
const inclusionCopy = (
  tab: CoverageTabKey,
  workspaceLabel: string,
  excludedDbuLabel: string,
) => {
  if (tab === "sql_warehouse") {
    return (
      <>
        On this tab, {workspaceLabel} run outside those subscriptions. Their{" "}
        {excludedDbuLabel} in Databricks DBU spend is <strong>excluded</strong>{" "}
        from the KPI totals on this tab and shown separately on each row with a
        “Not covered” badge. Serverless DBU includes infrastructure; Classic/Pro
        VM, disk, and network charges are not attributed on this tab.
      </>
    );
  }
  return (
    <>
      On this tab, {workspaceLabel} run outside those subscriptions. Their{" "}
      {excludedDbuLabel} in Databricks DBU spend is included, but their cloud
      infrastructure cost is not. These rows are labeled “Not covered.”
    </>
  );
};

/** Compact per-tab disclosure for Azure cloud-cost coverage. */
export function CoverageBanner({ tab, dateRange }: CoverageBannerProps) {
  const { data, isLoading, isError } = useCoverageSummary(dateRange);

  if (isLoading || isError || !data) {
    return null;
  }

  const excludedDbu = data.excluded_dbu_by_tab[tab] ?? 0;
  const excludedCount = data.excluded_workspace_count_by_tab[tab] ?? 0;

  if (excludedCount === 0 && excludedDbu <= 0) {
    return null;
  }

  const coveredSubCount = data.covered_subscription_ids.length;
  const exampleNames = formatExampleWorkspaceNames(data.excluded_workspaces);
  const excludedDbuLabel = currencyFormatter.format(excludedDbu);
  const subscriptionLabel = `${coveredSubCount} connected cloud billing ${
    coveredSubCount === 1 ? "scope" : "scopes"
  }`;
  const workspaceLabel =
    excludedCount > 0
      ? `${excludedCount} ${excludedCount === 1 ? "workspace" : "workspaces"}`
      : "workspaces with non-covered usage";

  return (
    <div className="flex justify-end">
      <Popover>
        <PopoverTrigger asChild>
          <button
            type="button"
            className="rounded-full p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            aria-label="View cloud cost coverage information"
          >
            <Info className="h-5 w-5" />
          </button>
        </PopoverTrigger>
        <PopoverContent align="end" className="w-96 space-y-2">
          <h3 className="font-semibold">Cloud cost coverage</h3>
          <p className="text-sm text-muted-foreground">
            Cloud infrastructure cost is available for workspaces in{" "}
            {subscriptionLabel}.
          </p>
          <p className="text-sm text-muted-foreground">
            {inclusionCopy(tab, workspaceLabel, excludedDbuLabel)}
          </p>
          {data.excluded_workspaces.length > 0 && (
            <p className="text-xs text-muted-foreground">
              Example non-covered workspaces across billing usage:{" "}
              {exampleNames}
            </p>
          )}
        </PopoverContent>
      </Popover>
    </div>
  );
}
