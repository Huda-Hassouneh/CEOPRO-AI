// No SDK load or provider request until explicit action and protected handoff.
export function paddleCheckoutOptions(details, operation, transaction, locale = 'en') {
  if (details?.operation_id !== operation || details.provider !== 'paddle' || details.environment !== 'test'
      || !/^txn_[a-z0-9]{26}$/.test(details.transaction_id) || details.transaction_id !== transaction) {
    throw new Error('Original sandbox transaction required');
  }
  return { transactionId: details.transaction_id, settings: { displayMode: 'overlay',
    allowLogout: false, allowedPaymentMethods: ['card'], locale: locale === 'ar' ? 'ar' : 'en' } };
}

let sdkLoad;
let initializedToken;
export async function openPaddleCheckout(details, operation, transaction, locale, config = { VITE_RECURRING_JOURNEY_ENABLED: import.meta.env?.VITE_RECURRING_JOURNEY_ENABLED,
  VITE_PADDLE_CHECKOUT_ENABLED: import.meta.env?.VITE_PADDLE_CHECKOUT_ENABLED,
  VITE_PADDLE_CLIENT_TOKEN: import.meta.env?.VITE_PADDLE_CLIENT_TOKEN,
  VITE_PADDLE_CHECKOUT_ORIGIN: import.meta.env?.VITE_PADDLE_CHECKOUT_ORIGIN }, signal) {
  if (config?.VITE_RECURRING_JOURNEY_ENABLED !== 'true' || config?.VITE_PADDLE_CHECKOUT_ENABLED !== 'true'
      || !/^test_[a-zA-Z0-9]+$/.test(config?.VITE_PADDLE_CLIENT_TOKEN || '')
      || config?.VITE_PADDLE_CHECKOUT_ORIGIN !== window.location.origin) throw new Error('Sandbox Checkout unavailable');
  if (signal?.aborted) throw new Error('Checkout canceled');
  const options = paddleCheckoutOptions(details, operation, transaction, locale);
  if (!sdkLoad) sdkLoad = new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = 'https://cdn.paddle.com/paddle/v2/paddle.js';
    script.onload = resolve; script.onerror = () => { sdkLoad = undefined; reject(new Error('Checkout unavailable')); };
    document.head.append(script);
  });
  await sdkLoad;
  if (signal?.aborted) throw new Error('Checkout canceled');
  const paddle = window.Paddle;
  if (!paddle || initializedToken && initializedToken !== config.VITE_PADDLE_CLIENT_TOKEN) throw new Error('Checkout unavailable');
  if (!initializedToken) {
    paddle.Environment.set('sandbox');
    // SDK may auto-open _ptxn on initialization. It has already been matched to
    // the authenticated server handoff; no URL price or Customer is accepted.
    paddle.Initialize({ token: config.VITE_PADDLE_CLIENT_TOKEN, checkout: { settings: options.settings } });
    initializedToken = config.VITE_PADDLE_CLIENT_TOKEN;
  }
  paddle.Checkout.open(options);
}
