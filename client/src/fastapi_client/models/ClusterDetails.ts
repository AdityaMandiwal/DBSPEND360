/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * Cluster configuration details from system.compute.clusters.
 */
export type ClusterDetails = {
    cluster_id: string;
    owned_by?: (string | null);
    create_time?: (string | null);
    driver_node_type?: (string | null);
    worker_node_type?: (string | null);
    worker_count?: (number | null);
    min_autoscale_workers?: (number | null);
    max_autoscale_workers?: (number | null);
    auto_termination_minutes?: (number | null);
    enable_elastic_disk?: (boolean | null);
    tags?: (Record<string, any> | null);
    aws_attributes?: (Record<string, any> | null);
    azure_attributes?: (Record<string, any> | null);
    gcp_attributes?: (Record<string, any> | null);
    dbr_version?: (string | null);
    data_security_mode?: (string | null);
};

