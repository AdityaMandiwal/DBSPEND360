import React, { createContext, useContext, useEffect, useState } from 'react';
import { AlertTriangle } from 'lucide-react';
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

/**
 * CP8 / MINOR-5 (§4.7): transparency-only banner.
 *
 * When `/api/cloud-platform` fails, the provider falls back to a neutral
 * `Unknown` platform and the §4.0 positive allowlist already renders the
 * always-correct 2-slice (cloud + DBU) view — so this banner is NOT needed for
 * correctness. It exists only so the degraded view isn't silent: the user is
 * told the provider config couldn't load and labels may be generic.
 */
export const CloudPlatformErrorBanner: React.FC = () => {
  const { config, error } = useCloudPlatform();

  if (!error || config?.platform !== 'Unknown') {
    return null;
  }

  return (
    <div
      role="alert"
      className="flex items-start gap-2 border-b border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-800 dark:border-amber-900/50 dark:bg-amber-950/40 dark:text-amber-200"
    >
      <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0" />
      <span>
        Couldn't load cloud platform config &mdash; showing a generic
        cloud-cost view. Provider-specific labels may be unavailable.
      </span>
    </div>
  );
};