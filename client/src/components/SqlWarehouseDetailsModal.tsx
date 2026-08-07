// SQL warehouse details modal — renders warehouse config, the period cost
// summary, and a warehouse-tuned LLM analysis (plan §3d).
//
// Mirrors `PipelineDetailsModal.tsx` with two simplifications: there is no
// `workspace_id` to disambiguate (`warehouse_id` is account-unique, so no 409
// path exists) and no cost-basis caveat — DBU is the complete cost for
// Databricks-managed compute, so nothing is missing from the number.
//
// The metadata banner is deliberately NEUTRAL: roughly three quarters of
// warehouses carry no `system.compute.warehouses` snapshot, so a missing
// config is the common case, not an error. Cost figures stay accurate either
// way, which is what the banner says.

import { AlertTriangle, Brain, Database, FileQuestion, Info, User } from 'lucide-react';
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
  useSqlWarehouseAnalysis,
  useSqlWarehouseDetails,
} from '@/hooks/useSqlWarehouses';
import {
  formatCurrency,
  warehouseTypeBadgeClasses,
  warehouseTypeLabel,
} from '@/lib/sql-warehouse-display';
import { useAiModelLabel } from '@/hooks/useJobSpends';
import { closeOnly, formatCalendarDate } from '@/lib/utils';
import { AnalysisMarkdown } from './AnalysisMarkdown';

// Cost figures for the currently selected window, passed down from the table
// row. `/details` is config-only, so the modal reuses the row it was opened
// from rather than issuing a second cost query.
export interface SqlWarehouseCostSummary {
  totalCost: number;
  databricksCost: number;
  activeDays: number;
  startDate: string;
  endDate: string;
}

interface SqlWarehouseDetailsModalProps {
  warehouseId: string;
  costSummary?: SqlWarehouseCostSummary;
  isOpen: boolean;
  onClose: () => void;
}

// `warehouse_deleted_at` is a timestamp; `formatCalendarDate` renders its
// LOCAL calendar day so the banner never shows the wrong date on negative-UTC
// zones.
const formatDeleteDate = (dateStr?: string | null): string | null =>
  dateStr
    ? formatCalendarDate(dateStr, {
        year: 'numeric',
        month: 'long',
        day: 'numeric',
      })
    : null;

// `auto_stop_mins = 0` means the warehouse never auto-stops — a real cost
// signal, so it reads as words rather than "0".
const formatAutoStop = (mins?: number | null): string => {
  if (mins == null) return 'N/A';
  if (mins === 0) return 'Never';
  return `${mins} min`;
};

const formatClusterRange = (
  min?: number | null,
  max?: number | null,
): string => {
  if (min == null && max == null) return 'N/A';
  return `${min ?? '?'} – ${max ?? '?'}`;
};

export const SqlWarehouseDetailsModal = ({
  warehouseId,
  costSummary,
  isOpen,
  onClose,
}: SqlWarehouseDetailsModalProps) => {
  const {
    data: details,
    isLoading: detailsLoading,
    error: detailsError,
  } = useSqlWarehouseDetails(warehouseId);
  // Only fire the (LLM-charging) analysis once details resolve successfully.
  const detailsResolved = !!details && !detailsError;
  const aiModelLabel = useAiModelLabel();
  const {
    data: analysis,
    isLoading: analysisLoading,
    error: analysisError,
  } = useSqlWarehouseAnalysis(warehouseId, { enabled: detailsResolved });

  const deletedDateLabel = formatDeleteDate(details?.warehouse_deleted_at);

  return (
    <Dialog open={isOpen} onOpenChange={closeOnly(onClose)}>
      <DialogContent className="max-w-5xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="text-xl font-semibold flex items-center gap-2">
            <Database className="h-5 w-5" />
            SQL Warehouse Configuration & Analysis
          </DialogTitle>
        </DialogHeader>

        {detailsError ? (
          <div className="text-center py-8">
            <div className="text-red-600 font-medium mb-2">
              Error loading warehouse details
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
            {details.warehouse_deleted_at && (
              <div className="flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-500/40 dark:bg-amber-500/10 dark:text-amber-200">
                <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
                <div>
                  <div className="font-semibold">
                    Warehouse deleted on {deletedDateLabel}.
                  </div>
                  <div className="text-xs mt-1 opacity-90">
                    Configuration shown is as of the delete time. Cost figures
                    remain accurate.
                  </div>
                </div>
              </div>
            )}
            {details.metadata_missing && !details.warehouse_deleted_at && (
              // Neutral grey, NOT alarming — most warehouses land here.
              <div className="flex items-start gap-2 rounded-md border bg-muted px-4 py-3 text-sm text-muted-foreground">
                <FileQuestion className="h-4 w-4 mt-0.5 shrink-0" />
                <div>
                  <div className="font-semibold text-foreground">
                    Metadata unavailable.
                  </div>
                  <div className="text-xs mt-1">
                    No row found in{' '}
                    <span className="font-mono">system.compute.warehouses</span>{' '}
                    — common for warehouses created before the system table
                    began recording, or outside its retention window. Cost
                    figures remain accurate; the configuration below is
                    unavailable.
                  </div>
                </div>
              </div>
            )}

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              {/* Warehouse configuration + cost summary */}
              <div className="space-y-4">
                <h3 className="text-lg font-semibold flex items-center">
                  <Database className="mr-2 h-5 w-5" />
                  Warehouse Configuration
                </h3>

                <div className="p-4 border rounded-lg space-y-3">
                  <div className="flex justify-between items-start">
                    <span className="text-sm font-medium text-muted-foreground">
                      Warehouse Name
                    </span>
                    <div className="text-right max-w-[260px]">
                      <div
                        className="text-sm font-medium truncate"
                        title={details.warehouse_name ?? undefined}
                      >
                        {details.warehouse_name ?? (
                          <span className="font-mono text-muted-foreground">
                            Warehouse {details.warehouse_id}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="flex justify-between items-start">
                    <span className="text-sm font-medium text-muted-foreground">
                      Warehouse ID
                    </span>
                    <div className="text-right">
                      <div
                        className="font-mono text-xs max-w-[260px] truncate"
                        title={details.warehouse_id}
                      >
                        {details.warehouse_id}
                      </div>
                    </div>
                  </div>

                  <div className="flex justify-between items-start">
                    <span className="text-sm font-medium text-muted-foreground">
                      Type
                    </span>
                    <div className="text-right max-w-[260px]">
                      {details.warehouse_type ? (
                        <Badge
                          variant="secondary"
                          className={`text-[10px] ${warehouseTypeBadgeClasses(
                            details.warehouse_type,
                          )}`}
                        >
                          {warehouseTypeLabel(details.warehouse_type)}
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
                      Size
                    </span>
                    <div className="text-right">
                      <div className="text-sm font-mono">
                        {details.warehouse_size ?? 'N/A'}
                      </div>
                    </div>
                  </div>

                  <div className="flex justify-between items-start">
                    <span className="text-sm font-medium text-muted-foreground">
                      Auto Stop
                    </span>
                    <div className="text-right">
                      <div className="text-sm">
                        {formatAutoStop(details.auto_stop_mins)}
                      </div>
                    </div>
                  </div>

                  <div className="flex justify-between items-start">
                    <span className="text-sm font-medium text-muted-foreground">
                      Cluster Scaling
                    </span>
                    <div className="text-right">
                      <div className="text-sm">
                        {formatClusterRange(
                          details.min_clusters,
                          details.max_clusters,
                        )}
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
                      Creator
                    </span>
                    <div className="text-right max-w-[260px]">
                      {details.creator_id ? (
                        <div
                          className="text-sm truncate"
                          title={details.creator_id}
                        >
                          {details.creator_id}
                        </div>
                      ) : (
                        <span className="text-sm italic text-muted-foreground">
                          Unknown
                        </span>
                      )}
                    </div>
                  </div>
                </div>

                {costSummary && (
                  <div className="p-4 border rounded-lg space-y-3">
                    <h4 className="font-semibold">Cost for Selected Period</h4>
                    <div className="text-xs text-muted-foreground">
                      {formatCalendarDate(costSummary.startDate)} to{' '}
                      {formatCalendarDate(costSummary.endDate)} ·{' '}
                      {costSummary.activeDays} active day
                      {costSummary.activeDays === 1 ? '' : 's'}
                    </div>
                    <div className="flex justify-between items-start">
                      <span className="text-sm font-medium text-muted-foreground">
                        DBU Cost
                      </span>
                      <div className="text-sm font-medium text-red-600">
                        {formatCurrency(costSummary.databricksCost)}
                      </div>
                    </div>
                    <div className="flex justify-between items-start">
                      <span className="text-sm font-medium text-muted-foreground">
                        Total Cost
                      </span>
                      <div className="text-sm font-bold">
                        {formatCurrency(costSummary.totalCost)}
                      </div>
                    </div>
                    <p className="text-xs text-muted-foreground">
                      SQL Warehouses run on Databricks-managed compute, so DBU
                      is the complete cost — there is no separate VM line.
                      Figures are list price and exclude account-level
                      discounts.
                    </p>
                  </div>
                )}

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

              {/* AI warehouse analysis */}
              <div className="space-y-4">
                <Card>
                  <CardHeader>
                    <CardTitle className="flex items-center text-lg">
                      <Brain className="mr-2 h-5 w-5 text-purple-600" />
                      AI Warehouse Analysis
                      <Badge variant="secondary" className="ml-2 text-xs">
                        Powered by {aiModelLabel}
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
              No warehouse details available
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
};
