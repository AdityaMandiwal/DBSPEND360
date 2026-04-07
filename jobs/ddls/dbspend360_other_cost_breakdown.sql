%sql
CREATE TABLE IF NOT EXISTS ${catalog}.${schema}.dbspend360_other_cost_breakdown (
  cost_incurred_date  DATE,
  cluster_id          STRING,
  source_system       STRING,
  service_name        STRING,
  cost                DOUBLE,
  currency            STRING,
  created_at          TIMESTAMP,
  updated_at          TIMESTAMP
)
CLUSTER BY AUTO
