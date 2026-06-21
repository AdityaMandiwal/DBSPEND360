-- CP13 — One-off AWS cost-accuracy data cleanup
-- Plan reference: docs/plan_aws_cost_accuracy_cleanup.md §5, D11.
--
-- Purpose: remove orphaned data left behind by the discarded
-- workspace-shared / reconciliation attempt (see §2.1 — that code never
-- shipped in the clean tree, but live history may still hold its artifacts).
--
-- Scope: AWS-only cleanup against the live UC schema `dbspend360.04june`.
-- Both statements are idempotent and existence-gated, so this file is safe to
-- re-run. It is intentionally NOT wired into the recurring DABs job — run it
-- once, by hand, against the SQL warehouse (warehouse_id=8baced1ff014912d).
--
-- This script does NOT touch the vestigial `scope` / `category` columns on
-- `dbspend360_other_cost_breakdown` (D11): they are unread by all code paths
-- (`get_other_cost_breakdown` selects explicit columns; `validate_source_schema`
-- checks presence, not absence) and Azure/GCP keep using the table.

-- (1) Drop the orphaned workspace-total table if it exists.
-- No code path reads or writes this table in the clean tree (§2.1); it only
-- ever existed in the discarded reconciliation attempt.
DROP TABLE IF EXISTS dbspend360.04june.dbspend360_workspace_total_costs;

-- (2) Delete orphaned workspace-shared breakdown rows.
-- Verified safe (§5.2): no code path writes `scope` (only the retired DDL
-- back-fill did), so this matches only orphaned rows. Azure/GCP cannot
-- legitimately produce `scope = 'workspace_shared'`, and the table itself is
-- retained for Azure/GCP per-cluster `other` breakdowns.
DELETE FROM dbspend360.04june.dbspend360_other_cost_breakdown
WHERE scope = 'workspace_shared';
