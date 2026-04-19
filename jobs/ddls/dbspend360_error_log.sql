%sql
CREATE TABLE IF NOT EXISTS ${catalog}.${schema}.dbspend360_error_log (
  source_system STRING,   -- 'AWS_COST' or 'AZURE_COST' or 'GCP_COST' or 'DBR_DBU'
  error_type    STRING,   -- e.g., 'NO_MATCH_DBR_DBU', 'NO_MATCH_AWS_COST', 'NO_MATCH_AZURE_COST', 'NO_MATCH_GCP_COST'
  cluster_id    STRING,
  job_id        STRING,
  run_id        STRING,
  usage_date    DATE,
  currency      STRING,
  error_detail  STRING,   -- free-text description
  raw_record    STRING,   -- JSON serialization of the problematic row
  created_at    TIMESTAMP
)
CLUSTER BY AUTO
