%sql
CREATE TABLE IF NOT EXISTS ${catalog}.${schema}.dbspend360_total_job_spends (
  cluster_id      STRING,
  job_id          STRING,
  run_id          STRING,
  usage_date      DATE,
  cloud_cost      DOUBLE,
  compute_cost    DOUBLE,
  storage_cost    DOUBLE,
  network_cost    DOUBLE,
  other_cost      DOUBLE,
  databricks_cost DOUBLE,
  currency        STRING,
  total_cost      DOUBLE,
  created_at      TIMESTAMP,
  updated_at      TIMESTAMP
)
CLUSTER BY AUTO