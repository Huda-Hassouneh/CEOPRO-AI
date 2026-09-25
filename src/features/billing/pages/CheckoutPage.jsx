import { useNavigate } from 'react-router-dom';
import { CreditCard } from 'lucide-react';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { routePaths } from '../../../app/router/routePaths.js';
import Button from '../../../shared/components/ui/Button.jsx';
import EmptyState from '../../../shared/components/ui/EmptyState.jsx';
import '../styles/Billing.css';

export function CheckoutPage() {
  const navigate = useNavigate();
  const { t } = useI18n();

  return (
    <EmptyState
      icon={<CreditCard size={28} />}
      title={t('billing.checkoutRoute.title')}
      description={t('billing.checkoutRoute.description')}
      action={<Button onClick={() => navigate(routePaths.choosePlan)}>{t('billing.checkoutRoute.action')}</Button>}
    />
  );
}
