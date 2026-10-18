import { BusinessAppShell, useBusinessShell } from '../../shared/components/layout/BusinessAppShell.jsx';
import '../../styles/business-shell.css';

export function DashboardLayout({ children }) {
  const insideShell = useBusinessShell();
  return insideShell ? children : <BusinessAppShell>{children}</BusinessAppShell>;
}
