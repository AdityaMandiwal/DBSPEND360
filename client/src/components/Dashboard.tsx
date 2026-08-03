import { useEffect, useState } from 'react';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { ThemeToggle } from './ThemeToggle';
import JobClustersDashboard from './JobClustersDashboard';
import AllPurposeDashboard from './AllPurposeDashboard';
import InstancePoolsDashboard from './InstancePoolsDashboard';
import PipelineDashboard from './PipelineDashboard';
import SqlWarehousesDashboard from './SqlWarehousesDashboard';

const VALID_TABS = [
  'job-clusters',
  'all-purpose',
  'instance-pools',
  'pipelines',
  'sql-warehouses',
] as const;
type TabValue = (typeof VALID_TABS)[number];
const DEFAULT_TAB: TabValue = 'job-clusters';

const readTabFromUrl = (): TabValue => {
  if (typeof window === 'undefined') return DEFAULT_TAB;
  const params = new URLSearchParams(window.location.search);
  const candidate = params.get('tab');
  return (VALID_TABS as readonly string[]).includes(candidate ?? '')
    ? (candidate as TabValue)
    : DEFAULT_TAB;
};

const Dashboard = () => {
  const [activeTab, setActiveTab] = useState<TabValue>(DEFAULT_TAB);

  useEffect(() => {
    setActiveTab(readTabFromUrl());
  }, []);

  const handleTabChange = (value: string) => {
    if (!(VALID_TABS as readonly string[]).includes(value)) return;
    const next = value as TabValue;
    setActiveTab(next);
    const params = new URLSearchParams(window.location.search);
    if (next === DEFAULT_TAB) {
      params.delete('tab');
    } else {
      params.set('tab', next);
    }
    const query = params.toString();
    const url = `${window.location.pathname}${query ? `?${query}` : ''}${window.location.hash}`;
    window.history.replaceState(null, '', url);
  };

  return (
    <div className="min-h-screen bg-background text-foreground">
      <div className="container mx-auto p-6 space-y-6">
        {/* Header */}
        <div className="flex items-start justify-between gap-4">
          <div className="flex flex-col space-y-2">
            <h1 className="text-3xl font-bold text-foreground">DBSpend360</h1>
            <p className="text-muted-foreground">
              Databricks Cost Analytics Dashboard
            </p>
          </div>
          <ThemeToggle />
        </div>

        {/* Top-level tabs */}
        <Tabs value={activeTab} onValueChange={handleTabChange} className="space-y-6">
          <TabsList>
            <TabsTrigger value="job-clusters">Job Clusters</TabsTrigger>
            <TabsTrigger value="all-purpose">All-Purpose Clusters</TabsTrigger>
            <TabsTrigger value="instance-pools">Instance Pools</TabsTrigger>
            <TabsTrigger value="pipelines">Pipeline Compute</TabsTrigger>
            <TabsTrigger value="sql-warehouses">SQL Warehouses</TabsTrigger>
          </TabsList>

          <TabsContent value="job-clusters" className="mt-0">
            <JobClustersDashboard />
          </TabsContent>

          <TabsContent value="all-purpose" className="mt-0">
            <AllPurposeDashboard />
          </TabsContent>

          <TabsContent value="instance-pools" className="mt-0">
            <InstancePoolsDashboard />
          </TabsContent>

          <TabsContent value="pipelines" className="mt-0">
            <PipelineDashboard />
          </TabsContent>

          <TabsContent value="sql-warehouses" className="mt-0">
            <SqlWarehousesDashboard />
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
};

export default Dashboard;
