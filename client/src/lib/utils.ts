import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

// Single source of truth for the "High Cost" badge threshold (USD). Used by
// both the job table and the job breakdown modal so a job is never flagged
// high-cost in one view and not the other (plan §4.4 / review #J4).
export const HIGH_COST_USD = 1000;

// Parse a YYYY-MM-DD calendar date as LOCAL midnight, never UTC midnight,
// so display never rolls back a day in negative-UTC timezones.
export function parseCalendarDate(dateStr: string): Date {
  return new Date(`${dateStr}T00:00:00`);
}

// Parse either a bare `YYYY-MM-DD` (anchored to local midnight) or a full
// timestamp (parsed as-is, already local). A bare date parsed via the native
// `Date` constructor would be read as UTC midnight and can roll back a day in
// negative-UTC zones; the anchor avoids that. Timestamps keep their time
// component so `new Date(...)` resolves the correct local calendar day.
export function parseDateOrTimestamp(value: string): Date {
  return /^\d{4}-\d{2}-\d{2}$/.test(value)
    ? parseCalendarDate(value)
    : new Date(value);
}

export function formatCalendarDate(
  dateStr: string,
  opts: Intl.DateTimeFormatOptions = {
    year: "numeric",
    month: "short",
    day: "numeric",
  },
): string {
  try {
    return parseDateOrTimestamp(dateStr).toLocaleDateString("en-US", opts);
  } catch {
    return dateStr;
  }
}

// Format a calendar date or timestamp as a LOCAL `YYYY-MM-DD` string. Use for
// ISO-style badge labels instead of `new Date(x).toISOString().slice(0, 10)`,
// which forces UTC and can render the wrong day in negative-UTC zones.
export function formatLocalISODate(value: string): string {
  try {
    const d = parseDateOrTimestamp(value);
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${y}-${m}-${day}`;
  } catch {
    return value;
  }
}

// Cheap client-side guard so an inverted date range gets immediate inline
// feedback instead of relying on the API's 400 (plan §8 poly5). Calendar dates
// are `YYYY-MM-DD`, so a lexical string compare is equivalent to a date compare.
export function isInvalidDateRange(
  startDate: string,
  endDate: string,
): boolean {
  return !!startDate && !!endDate && startDate > endDate;
}

// A range is safe to query only when both ends are present AND not inverted
// (start <= end). React Query `enabled` clauses use this so an inverted range
// never fires a request the API would reject with a 400 (plan §8 poly5).
export function canQueryRange(startDate?: string, endDate?: string): boolean {
  return !!(startDate && endDate) && !isInvalidDateRange(startDate, endDate);
}

// Radix `Dialog`/`Sheet` `onOpenChange` passes a boolean; callers usually only
// want to fire their close handler when the surface is closing. This adapts a
// plain `() => void` close callback to the boolean signature safely.
export const closeOnly =
  (onClose: () => void) =>
  (open: boolean): void => {
    if (!open) onClose();
  };
