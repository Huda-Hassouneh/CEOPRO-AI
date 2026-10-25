// Preserve existing owner review/policy links while using the original shell.
export const ownerBillingDestination = (location) => ({
  pathname: '/admin/billing',
  search: location?.search || '',
  hash: location?.hash || '',
});
