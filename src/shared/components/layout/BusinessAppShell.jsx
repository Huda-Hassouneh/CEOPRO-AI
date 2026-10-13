import { createContext, useContext, useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import TopNav from './TopNav.jsx';

const ShellContext = createContext(false);

export function BusinessAppShell({ children }) {
  const { pathname } = useLocation();
  useEffect(() => { window.scrollTo({ top: 0 }); }, [pathname]);

  // Keyed by path so each screen plays the entrance transition.
  return <ShellContext.Provider value><div className="business-app-shell">
    <TopNav />
    <main className="business-app-shell__main" id="main-content"><div className="apex-route" key={pathname}>{children}</div></main>
  </div></ShellContext.Provider>;
}

export function useBusinessShell() {
  return useContext(ShellContext);
}
