import { RouterProvider } from 'react-router-dom';
import { router } from './app/router/index.jsx';
import { AuthProvider } from './app/providers/AuthProvider.jsx';
import { I18nProvider } from './app/providers/I18nProvider.jsx';
import { QueryProvider } from './app/providers/QueryProvider.jsx';
import { ThemeProvider } from './app/providers/ThemeProvider.jsx';

export default function App() {
  return (
    <ThemeProvider>
      <QueryProvider>
        <I18nProvider>
          <AuthProvider>
            <RouterProvider router={router} />
          </AuthProvider>
        </I18nProvider>
      </QueryProvider>
    </ThemeProvider>
  );
}
