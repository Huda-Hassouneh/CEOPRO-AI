import { lazy, Suspense } from 'react';
import { RoutePending } from './RoutePending.jsx';

// Each screen is its own chunk, loaded when first visited; the shell around
// it stays on screen meanwhile. Once the app is idle the rest are fetched in
// the background so later navigation doesn't wait.
const loaders = [];
export function page(load) {
  loaders.push(load);
  const Lazy = lazy(load);
  return function LazyPage(props) {
    return <Suspense fallback={<RoutePending />}><Lazy {...props} /></Suspense>;
  };
}
let prefetched = false;
export function prefetchScreens() {
  if (prefetched) return;
  prefetched = true;
  // Every screen is ~300 kB: not on a metered or very slow connection, where
  // each screen still loads when it is opened.
  const connection = navigator.connection;
  if (connection && (connection.saveData || /(^|-)2g$/.test(connection.effectiveType || ''))) return;
  const run = () => loaders.forEach((load) => load().catch(() => {}));
  if ('requestIdleCallback' in window) window.requestIdleCallback(run, { timeout: 4000 });
  else setTimeout(run, 2500);
}
