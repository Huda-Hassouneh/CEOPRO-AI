// The event is persisted by the verified payment authority, never by acceptance.
export const quoteHasVerifiedActivation = (quote) => Boolean(
  quote?.events?.some((event) => event.action === 'contract_activated'),
);
