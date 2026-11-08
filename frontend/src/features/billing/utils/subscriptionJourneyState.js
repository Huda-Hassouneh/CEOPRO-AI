export function journeyState(progress, advance) {
  if (progress.isError) return 'blocked';
  const durable = progress.data?.state;
  if (['confirmed', 'conflict', 'expired', 'blocked'].includes(durable)) return durable;
  return advance.data?.state || durable || 'pending';
}


export function journeyCheckoutUrl(data, paddleOrigin = import.meta.env?.VITE_PADDLE_CHECKOUT_ORIGIN) {
  if (data?.state !== 'checkout_ready' || !data.url) return null;
  try {
    const url = new URL(data.url);
    if (url.protocol !== 'https:' || url.username || url.password) return null;
    if ((data.provider || 'stripe') === 'stripe' && url.hostname === 'checkout.stripe.com') return url.href;
    if (data.provider === 'paddle' && paddleOrigin && url.origin === paddleOrigin) return url.href;
  } catch { /* A malformed provider URL is never navigation authority. */ }
  return null;
}
