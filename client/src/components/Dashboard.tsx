import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ThemeToggle } from "./ThemeToggle";
import { JobsTab } from "./JobsTab";
import { SharedClustersTab } from "./SharedClustersTab";
import { InstancePoolsTab } from "./InstancePoolsTab";
import { DashboardProvider } from "./DashboardContext";
import { useCloudPlatform } from "@/contexts/CloudPlatformContext";

const Dashboard = () => {
  const { config } = useCloudPlatform();
  // Default to enabled when the config hasn't loaded yet — tabs are
  // hidden only when an environment explicitly flips the feature flag off
  // (e.g. while waiting for the slice 2 / slice 3 backfills).
  const showSharedClusters = config?.enable_shared_clusters_tab ?? true;
  const showInstancePools = config?.enable_instance_pools_tab ?? true;

  return (
    <DashboardProvider>
      <div className="min-h-screen bg-background text-foreground">
        <div className="container mx-auto p-6 space-y-6">
          <div className="flex items-start justify-between gap-4">
            <div className="flex flex-col space-y-2">
              <h1 className="text-3xl font-bold text-foreground">DBSpend360</h1>
              <p className="text-muted-foreground">
                Databricks Compute Cost Analytics Dashboard
              </p>
            </div>
            <ThemeToggle />
          </div>

          <Tabs defaultValue="jobs" className="space-y-4">
            <TabsList>
              <TabsTrigger value="jobs">Jobs</TabsTrigger>
              {showSharedClusters && (
                <TabsTrigger value="shared-clusters">
                  Shared Clusters
                </TabsTrigger>
              )}
              {showInstancePools && (
                <TabsTrigger value="instance-pools">Instance Pools</TabsTrigger>
              )}
            </TabsList>

            <TabsContent value="jobs">
              <JobsTab />
            </TabsContent>

            {showSharedClusters && (
              <TabsContent value="shared-clusters">
                <SharedClustersTab />
              </TabsContent>
            )}

            {showInstancePools && (
              <TabsContent value="instance-pools">
                <InstancePoolsTab />
              </TabsContent>
            )}
          </Tabs>
        </div>
      </div>
    </DashboardProvider>
  );
};

export default Dashboard;
