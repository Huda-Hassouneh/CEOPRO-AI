import { useEffect } from 'react';
import { isRouteErrorResponse, useRouteError } from 'react-router-dom';
import { AlertTriangle, RefreshCw } from 'lucide-react';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { reportError } from '../../lib/errorTracking.js';

// After a new release, a browser still holding the previous version can
// fail to load a code chunk that no longer exists - a reload fixes it.
const isStaleChunk = (error) => /dynamically imported module|Importing a module script failed|Failed to fetch dynamically|ChunkLoadError/i
  .test(String(error?.message || error));

// Also rendered directly (notFound) for addresses that match no screen.
export function AppErrorPage({ notFound: forcedNotFound = false }) {
  const error = useRouteError();
  const { t, dir } = useI18n();
  const notFound = forcedNotFound || (isRouteErrorResponse(error) && error.status === 404);
  const stale = isStaleChunk(error);
  if (error && !notFound) console.error('KEEL screen error:', error);
  // A stale chunk after a release is fixed by reloading; not worth reporting.
  useEffect(() => { if (error && !notFound && !stale) reportError(error); }, [error, notFound, stale]);
  const key = notFound ? 'notFound' : stale ? 'updated' : 'unexpected';
  return (
    <main className="apex-error-page" dir={dir} role="alert">
      <div className="apex-error-page__card">
        <span className="apex-error-page__icon" aria-hidden="true"><AlertTriangle size={26} /></span>
        <h1>{t(`appError.${key}.title`)}</h1>
        <p>{t(`appError.${key}.description`)}</p>
        <div className="apex-error-page__actions">
          {!notFound && <button type="button" className="apex-error-page__primary" onClick={() => window.location.reload()}><RefreshCw size={15} aria-hidden="true" />{t('appError.reload')}</button>}
          <a className="apex-error-page__secondary" href="/dashboard">{t('appError.home')}</a>
        </div>
      </div>
    </main>
  );
}

export default AppErrorPage;
