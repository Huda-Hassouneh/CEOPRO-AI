import { BusinessAppShell, useBusinessShell } from '../../shared/components/layout/BusinessAppShell.jsx';
import { useEffect } from 'react';
import { prefetchScreens } from '../router/lazyPage.jsx';
import '../../styles/business-shell.css';

export function DashboardLayout({ children }) {
  const insideShell = useBusinessShell();
  useEffect(() => { prefetchScreens(); }, []);
  return insideShell ? children : <BusinessAppShell>{children}</BusinessAppShell>;
}
