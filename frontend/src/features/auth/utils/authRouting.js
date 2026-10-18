import { routePaths } from '../../../app/router/routePaths.js';

export function getPostLoginDestination(routeState) {
  const attemptedDestination = routeState?.from;
  const candidate = typeof attemptedDestination === 'string'
    ? attemptedDestination
    : attemptedDestination?.pathname
      ? `${attemptedDestination.pathname}${attemptedDestination.search || ''}${attemptedDestination.hash || ''}`
      : null;

  return candidate?.startsWith('/') && !candidate.startsWith('//')
    ? candidate
    : routePaths.dashboard;
}
