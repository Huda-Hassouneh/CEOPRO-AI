import { routePaths } from '../../../app/router/routePaths.js';

// Signing in always opens the Dashboard - the page that says how the
// business is doing - rather than whichever page a session expired on.
// The only exceptions finish something the person started: accepting a
// team invitation and returning from checkout to Billing.
const RESUME_PREFIXES = [routePaths.invitation.split('/:')[0], routePaths.billing, '/platform'];

export function getPostLoginDestination(routeState) {
  const attemptedDestination = routeState?.from;
  const candidate = typeof attemptedDestination === 'string'
    ? attemptedDestination
    : attemptedDestination?.pathname
      ? `${attemptedDestination.pathname}${attemptedDestination.search || ''}${attemptedDestination.hash || ''}`
      : null;

  const safe = candidate?.startsWith('/') && !candidate.startsWith('//');
  return safe && RESUME_PREFIXES.some((prefix) => prefix && candidate.startsWith(prefix))
    ? candidate
    : routePaths.dashboard;
}
