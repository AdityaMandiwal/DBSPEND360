# Claude Scripts

This folder contains test scripts created by Claude for testing functionality and exploring the codebase.

## Purpose

Claude creates scripts in this folder to:
- Test database connections and queries
- Validate API endpoints and functionality
- Explore data structures and schemas
- Debug issues and verify implementations
- Prototype new features before integration

## Current Scripts

### `test_spark_query.py`
Tests Databricks table access using Spark SQL with serverless compute.
- Connects to Databricks using serverless compute
- Queries the first row from a specified table
- Displays schema information and data
- Includes fallback error handling and table exploration

### `test_sql_query.py`
Tests Databricks table access using SQL warehouses.
- Uses Databricks SDK for SQL warehouse connections
- Executes SQL queries through warehouse endpoints
- Displays results and schema information
- Includes warehouse management and error handling

### `aws_cost_recon_assert.py`
CP10 pre-merge reconciliation gate for the AWS `DEFAULT_SERVICES` shrink
(`docs/plan_aws_cost_accuracy_cleanup.md` §4.8(a)). Runs the same Cost Explorer
query over one window with the current 7-entry service filter vs. the proposed
2-entry EC2 pair and asserts the tagged (`ClusterId` non-empty) total is
unchanged — proving the shrink drops no cluster-attributable cost. Must pass
before the §4.1 ETL change (CP11) lands. Uses the `dbspend-read-ce` Databricks
service credential when run on Databricks; falls back to default boto3
credential resolution locally (needs `ce:GetCostAndUsage`).

```bash
# Match the §1 evidence window
uv run claude_scripts/aws_cost_recon_assert.py --start 2026-06-17 --end 2026-06-20

# Default window = last 3 complete UTC days
uv run claude_scripts/aws_cost_recon_assert.py
```

Exit code 0 = reconciliation passed; 1 = a dropped service carries tagged cost.

### `aws_cost_cleanup.sql`
CP13 one-off data cleanup for the AWS cost-accuracy work
(`docs/plan_aws_cost_accuracy_cleanup.md` §5, D11). Removes orphaned artifacts
left by the discarded workspace-shared / reconciliation attempt against the live
UC schema `dbspend360.04june`:
- `DROP TABLE IF EXISTS ... dbspend360_workspace_total_costs` (orphaned table,
  unread by all code paths).
- `DELETE FROM ... dbspend360_other_cost_breakdown WHERE scope =
  'workspace_shared'` (orphaned rows; the shared table itself is kept for
  Azure/GCP).

Both statements are idempotent and existence-gated, so the file is safe to
re-run. The vestigial `scope` / `category` columns are intentionally left in
place. This is a hand-run, one-off cleanup — NOT wired into the recurring DABs
job. Run against the SQL warehouse, e.g.:

```bash
databricks sql query --warehouse-id 8baced1ff014912d --file claude_scripts/aws_cost_cleanup.sql
```

(or paste the statements into the Databricks SQL editor).

## Usage

These scripts are designed to be run from the project root directory:

```bash
# Run with uv (recommended)
uv run claude_scripts/test_spark_query.py
uv run claude_scripts/test_sql_query.py

# Or with python directly
python claude_scripts/test_spark_query.py
python claude_scripts/test_sql_query.py
```

## Requirements

Scripts in this folder may require:
- Databricks authentication (token or profile)
- Specific Python dependencies (automatically handled by uv)
- Access to Databricks resources (warehouses, clusters, tables)

## Note

These scripts are for testing and exploration purposes. They should not be used in production environments.