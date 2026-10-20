import { useState } from 'react';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { ApexButton, StateBlock } from '../../../shared/components/apex/Apex.jsx';
import Toast from '../../../shared/components/ui/Toast.jsx';
import { useComparisonOverride, usePriceLadder, useSetPremiumBand } from '../hooks/usePriceComparisons.js';
import { PriceLadder } from './PriceLadder.jsx';

// Fetches and shows one product's comparison ladder (used by the Pricing compare dialog and the product page).
export function ProductPriceLadder({ productId }) {
  const { t } = useI18n();
  const query = usePriceLadder(productId);
  const override = useComparisonOverride(productId);
  const band = useSetPremiumBand();
  const [notice, setNotice] = useState(null);
  const setBand = (category, bandPct) => band.mutate({ category, bandPct }, {
    onSuccess: () => setNotice({ variant: 'success', message: t('pricing.ladder.guidance.saved') }),
    onError: (error) => setNotice({ variant: 'error', message: t(error?.response?.status === 403 ? 'pricing.ladder.decide.forbidden' : 'pricing.ladder.decide.failed') }),
  });
  const decide = (item, verdict) => override.mutate({ competitorId: item.competitor_id, itemName: item.item_name, verdict }, {
    onSuccess: () => setNotice({ variant: 'success', message: t('pricing.ladder.decide.saved') }),
    onError: (error) => setNotice({ variant: 'error', message: t(error?.response?.status === 403 ? 'pricing.ladder.decide.forbidden' : 'pricing.ladder.decide.failed') }),
  });
  if (query.isPending) return <StateBlock kind="loading" compact title={t('pricing.ladder.loading')} />;
  if (query.isError) {
    return <StateBlock kind="error" compact title={t('pricing.ladder.loadError')} action={<ApexButton size="sm" variant="secondary" onClick={() => query.refetch()}>{t('pricing.list.retry')}</ApexButton>} />;
  }
  return <>
    <PriceLadder ladder={query.data} onDecide={decide} onSetBand={setBand} busy={override.isPending || band.isPending} />
    {notice && <Toast variant={notice.variant} message={notice.message} onClose={() => setNotice(null)} />}
  </>;
}

export default ProductPriceLadder;
