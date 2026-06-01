# Architectural decisions locked-in before Slices 2 and 3

[← back to plan index](README.md)

These were teased out during the codebase verification pass. Each one closes off a class of design questions that would otherwise stall implementation mid-slice.

1. **Idle pool cost is computed by subtraction, not row classification.** `idle_cloud_cost(pool, date) = pool_tag_total − sum(attached_cluster_tag_total)` where `attached_cluster_tag_total` sums over every `cluster_id` whose `worker_instance_pool_id` or `driver_instance_pool_id` equals this pool on that date. Trying to classify each CE/Azure-CM line item as exclusively-idle vs exclusively-active is impossible because CE only returns one tag value per row given the GroupBy slot constraint (see decision #2). (Note: the `system.compute.clusters` worker column is named `worker_instance_pool_id`, not `instance_pool_id` — confirmed by slice 0.)

2. **Cloud-cost ETL gains a parallel CE/Azure-CM query path keyed on `DatabricksInstancePoolId`.** AWS CE allows exactly 2 `GroupBy` keys and both are already used (`TAG ClusterId` + `DIMENSION SERVICE`); Azure CM uses `TagKey + MeterCategory`. We cannot pull both tags in one call. The new path issues a second query, parses the same way, and lands rows with `cluster_id = NULL, instance_pool_id = <value>`. API quota and ETL runtime for the cloud-cost task roughly doubles — call this out in the audit log.

3. **`system.compute.clusters` grant becomes required for the new tabs.** Currently flagged as optional in README §"Optional: System Table Access". Without it the Shared Clusters tab has no owner / security-mode / auto-termination columns, and the Instance Pools tab cannot resolve pool↔cluster attachment for the subtraction in #1. We elevate the grant to required for the new tabs and document an explicit degraded mode (cluster IDs only, no config join) when the grant is unavailable.

4. **All new fact tables carry `workspace_id`.** `dbspend360_dbu_cost` already does, and the `workspace_ids` widget in `DBSPEND360.yaml` filters every existing ETL. Skipping the column in the new tables would silently break multi-workspace deployments.

5. **Pool LLM prompt follows the existing rubric pattern.** No absolute-dollar or absolute-percent thresholds in the system prompt body. Data goes in the user message, classification ("CRITICAL / NEEDS ATTENTION / WELL-OPTIMIZED") happens via a rubric mirroring `CLUSTER_ANALYSIS_SYSTEM_PROMPT`, with strict immutable section headers and a structured fallback builder.
