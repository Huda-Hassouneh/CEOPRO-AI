import { QueryClientProvider } from '@tanstack/react-query';
import { queryClient } from '../../shared/lib/queryClient.js';

export function QueryProvider({ children }) {
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}
