import { RouterProvider } from 'react-router-dom';
import { router } from './app/router/index.jsx';
import { AuthProvider } from './app/providers/AuthProvider.jsx';
import { I18nProvider } from './app/providers/I18nProvider.jsx';
import { QueryProvider } from './app/providers/QueryProvider.jsx';
import { WebSocketProvider } from './app/providers/WebSocketProvider.jsx';

export default function App() {
  return (
    <QueryProvider>
      <I18nProvider>
        <AuthProvider>
          <WebSocketProvider>
            <RouterProvider router={router} />
          </WebSocketProvider>
        </AuthProvider>
      </I18nProvider>
    </QueryProvider>
  );
}
