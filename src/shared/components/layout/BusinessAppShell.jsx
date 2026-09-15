import { createContext, useContext, useEffect, useState } from 'react';
import Sidebar from './Sidebar.jsx';
import Topbar from './Topbar.jsx';

const ShellContext = createContext(false);

export function BusinessAppShell({ children }) {
  const [sidebarOpen, setSidebarOpen] = useState(false);

  useEffect(() => {
    if (!sidebarOpen) return undefined;
    const closeOnEscape = (event) => {
      if (event.key === 'Escape') setSidebarOpen(false);
    };
    document.addEventListener('keydown', closeOnEscape);
    return () => document.removeEventListener('keydown', closeOnEscape);
  }, [sidebarOpen]);

  return <ShellContext.Provider value><div className="business-app-shell">
    <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />
    {sidebarOpen && <button type="button" className="business-shell-backdrop" onClick={() => setSidebarOpen(false)} aria-label="Close navigation" />}
    <div className="business-app-shell__body"><Topbar onMenuClick={() => setSidebarOpen(true)} /><main className="business-app-shell__main">{children}</main></div>
  </div></ShellContext.Provider>;
}

export function useBusinessShell() {
  return useContext(ShellContext);
}
