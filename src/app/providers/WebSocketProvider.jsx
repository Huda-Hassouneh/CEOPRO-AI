import { createContext, useContext, useEffect, useMemo, useState } from 'react';
import { WebSocketClient } from '../../shared/lib/websocketClient.js';
import { useAuthStore, selectIsAuthenticated } from '../../features/auth/store/authStore.js';

const WebSocketContext = createContext(null);

export function WebSocketProvider({ children }) {
  const [client] = useState(() => new WebSocketClient());
  const [connected, setConnected] = useState(false);
  const isHydrated = useAuthStore((state) => state.isHydrated);
  const isAuthenticated = useAuthStore(selectIsAuthenticated);

  useEffect(() => {
    if (!isHydrated || !isAuthenticated) {
      client.disconnect();
      setConnected(false);
      return undefined;
    }

    const socket = client.connect();
    socket.onopen = () => setConnected(true);
    socket.onclose = () => setConnected(false);
    socket.onerror = () => setConnected(false);

    return () => client.disconnect();
  }, [client, isAuthenticated, isHydrated]);

  const value = useMemo(() => ({ client, connected }), [client, connected]);

  return <WebSocketContext.Provider value={value}>{children}</WebSocketContext.Provider>;
}

export function useWebSocket() {
  return useContext(WebSocketContext);
}
