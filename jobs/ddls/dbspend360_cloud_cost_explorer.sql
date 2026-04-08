%sql
CREATE TABLE IF NOT EXISTS ${catalog}.${schema}.dbspend360_cloud_cost_explorer (
  cluster_id          STRING,
  cloud_cost          DOUBLE,
  compute_cost        DOUBLE,
  storage_cost        DOUBLE,
  network_cost        DOUBLE,
  other_cost          DOUBLE,
  currency            STRING,
  created_at          TIMESTAMP,
  updated_at          TIMESTAMP,
  cost_incurred_date  DATE
)
CLUSTER BY AUTO
