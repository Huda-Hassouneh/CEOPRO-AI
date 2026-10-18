const firstValue = (...values) => values.find((value) => typeof value === 'string' && value.trim())?.trim() || '';

export function getAccountProfile(user, t) {
  const personName = firstValue(user?.displayName, user?.fullName, user?.name, user?.profile?.displayName, user?.profile?.fullName, user?.profile?.name);
  const companyName = firstValue(
    user?.companyName,
    user?.businessName,
    user?.company?.name,
    user?.organization?.name,
    user?.profile?.companyName,
    user?.profile?.businessName,
  );
  const email = firstValue(user?.email, user?.emailAddress, user?.profile?.email);
  const avatarUrl = firstValue(user?.avatarUrl, user?.avatar, user?.picture, user?.profile?.avatarUrl);
  const identity = personName || companyName;
  const initials = identity
    ? identity.split(/\s+/u).slice(0, 2).map((part) => part[0]).join('').toLocaleUpperCase()
    : '?';

  return {
    personName: personName || t('onboarding.account.notAvailable'),
    companyName: companyName || t('onboarding.account.notAvailable'),
    email: email || t('onboarding.account.notAvailable'),
    avatarUrl,
    initials,
  };
}
