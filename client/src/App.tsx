import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import Dashboard from './components/Dashboard';
import { CloudPlatformProvider } from './contexts/CloudPlatformContext';
import { ThemeProvider } from './contexts/ThemeContext';

// Create a client
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5 * 60 * 1000, // 5 minutes
      cacheTime: 10 * 60 * 1000, // 10 minutes
      retry: 2,
      refetchOnWindowFocus: false,
    },
  },
});

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <CloudPlatformProvider>
          <Dashboard />
        </CloudPlatformProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}

export default App;
