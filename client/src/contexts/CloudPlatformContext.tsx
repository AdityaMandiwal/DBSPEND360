import React, { createContext, useContext, useEffect, useState } from 'react';
import { apiClient } from '@/lib/api-client';
import { CloudPlatformConfig } from '@/types/job-spend';

interface CloudPlatformContextType {
  config: CloudPlatformConfig | null;
  loading: boolean;
  error: string | null;
}

const CloudPlatformContext = createContext<CloudPlatformContextType>({
  config: null,
  loading: true,
  error: null,
});

export const useCloudPlatform = () => {
  const context = useContext(CloudPlatformContext);
  if (!context) {
    throw new Error('useCloudPlatform must be used within a CloudPlatformProvider');
  }
  return context;
};

interface CloudPlatformProviderProps {
  children: React.ReactNode;
}

export const CloudPlatformProvider: React.FC<CloudPlatformProviderProps> = ({ children }) => {
  const [config, setConfig] = useState<CloudPlatformConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchConfig = async () => {
      try {
        setLoading(true);
        const response = await apiClient.getCloudPlatformConfig();
        setConfig(response);
        setError(null);
      } catch (err) {
        console.error('Failed to fetch cloud platform config:', err);
        // Surface the failure via neutral placeholder + error state instead
        // of silently mislabeling the dashboard as AWS / EC2. UI components
        // should render `compute_display_name` and check `error` so they can
        // show a banner rather than a wrong provider name.
        setConfig({
          platform: 'Unknown',
          compute_service: 'Cloud',
          compute_display_name: 'Cloud Cost',
          platform_display_name: 'Unknown Cloud',
        });
        setError(
          err instanceof Error
            ? `Failed to fetch cloud platform config: ${err.message}`
            : 'Failed to fetch cloud platform config'
        );
      } finally {
        setLoading(false);
      }
    };

    fetchConfig();
  }, []);

  return (
    <CloudPlatformContext.Provider value={{ config, loading, error }}>
      {children}
    </CloudPlatformContext.Provider>
  );
};