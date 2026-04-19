%sql
CREATE TABLE IF NOT EXISTS ${catalog}.${schema}.dbspend360_audit_log (
  table_name STRING,    -- e.g. 'aws_cost_explorer', 'azure_cost_explorer', 'gcp_cost_explorer'
  start_date DATE,      -- start_dt used in the API call
  end_date   DATE,      -- end_dt used in the API call
  status     STRING,    -- 'SUCCESS', 'FAILED', 'SKIPPED'
  row_count  LONG,      -- rows merged into target (optional)
  message    STRING,    -- optional notes / error summary
  created_at TIMESTAMP  -- log insertion time
)
CLUSTER BY AUTO
