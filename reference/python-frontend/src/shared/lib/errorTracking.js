// Error tracking (Sentry) for the browser app, off unless VITE_SENTRY_DSN is
// set at build time. The Sentry library is only downloaded when it is on,
// so the normal bundle doesn't grow.
//
// Reports uncaught errors and unhandled promise rejections automatically,
// plus screen crashes passed to reportError(). Never sent: user details,
// cookies, request headers, query strings (they can carry codes and
// tokens) or console output.

const DSN = import.meta.env?.VITE_SENTRY_DSN;
let sentry = null;
const reported = new WeakSet();
const pending = [];

const stripQuery = (url) => (typeof url === 'string' ? url.split('?')[0].split('#')[0] : url);

export function scrubEvent(event) {
  delete event.user;
  if (event.request) {
    delete event.request.headers;
    delete event.request.cookies;
    delete event.request.query_string;
    event.request.url = stripQuery(event.request.url);
  }
  return event;
}

export function scrubBreadcrumb(breadcrumb) {
  if (breadcrumb.category === 'console') return null;
  if (breadcrumb.data?.url) breadcrumb.data.url = stripQuery(breadcrumb.data.url);
  if (breadcrumb.data?.to) breadcrumb.data.to = stripQuery(breadcrumb.data.to);
  if (breadcrumb.data?.from) breadcrumb.data.from = stripQuery(breadcrumb.data.from);
  return breadcrumb;
}

export async function initErrorTracking() {
  if (!DSN || sentry) return false;
  const Sentry = await import('@sentry/react');
  Sentry.init({
    dsn: DSN,
    environment: import.meta.env.VITE_SENTRY_ENVIRONMENT || 'production',
    release: import.meta.env.VITE_SENTRY_RELEASE || undefined,
    sendDefaultPii: false,
    beforeSend: scrubEvent,
    beforeBreadcrumb: scrubBreadcrumb,
  });
  Sentry.setTag('service', 'frontend');
  sentry = Sentry;
  pending.splice(0).forEach((error) => Sentry.captureException(error));
  return true;
}

// A screen crash caught by the router's error page. Errors that happen
// before tracking has loaded are queued and sent once it has.
export function reportError(error) {
  if (!DSN || !error || (typeof error === 'object' && reported.has(error))) return;
  if (typeof error === 'object') reported.add(error);
  if (sentry) sentry.captureException(error);
  else pending.push(error);
}
