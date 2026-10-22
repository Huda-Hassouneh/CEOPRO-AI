// Links built from data that came from outside KEEL (competitor websites found on public maps,
// news and search results, source pages) must never carry a script. React does not block a
// `javascript:` or `data:` address in an href, so clicking one would run it inside the app, where
// it could read the signed-in session. Only http(s) addresses are linked; anything else renders as
// an inert anchor (no href).
export function safeHref(url) {
  if (typeof url !== 'string') return undefined;
  const trimmed = url.trim();
  return /^https?:\/\//i.test(trimmed) ? trimmed : undefined;
}
