import { useEffect, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, Bell, Info, PackageX, Radar, Tag, TrendingDown, TrendingUp, CreditCard, FileWarning } from 'lucide-react';
import { useI18n } from '../../app/providers/I18nProvider.jsx';
import httpClient from '../../shared/lib/httpClient.js';

export const ICONS = {
  competitor_price: (a) => (a.params.change_pct < 0 ? TrendingDown : TrendingUp),
  restock: () => PackageX, price_gap: () => Tag, new_competitors: () => Radar,
  import_failed: () => FileWarning, payment_failed: () => CreditCard, trial_ending: () => CreditCard,
};

// One alert in words (the bell and the dashboard's recent updates).
export function describeAlert(a, t, number, money) {
  const p = a.params;
  switch (a.kind) {
    case 'competitor_price': return t(`alerts.competitor_price.${p.change_pct < 0 ? 'down' : 'up'}`, { competitor: p.competitor, product: p.product, price: money(p.price, p.currency), pct: number.format(Math.abs(p.change_pct)) });
    case 'restock': return t('alerts.restock', { product: p.product, days: number.format(p.days ?? 0), quantity: number.format(p.quantity ?? 0) });
    case 'price_gap': return t(`alerts.price_gap.${p.gap_pct > 0 ? 'above' : 'below'}`, { product: p.product, pct: number.format(Math.abs(p.gap_pct)), competitor: p.competitor });
    case 'new_competitors': return t('alerts.new_competitors', { count: p.count, tracked: p.tracked });
    case 'import_failed': return t('alerts.import_failed', { name: p.name || '' });
    case 'trial_ending': return t('alerts.trial_ending', { days: p.days });
    case 'payment_failed': return t('alerts.payment_failed');
    default: return a.kind;
  }
}

// The top bar's alerts: what needs attention now, from live data (/alerts).
export function AlertsBell({ open, onToggle, onClose }) {
  const { t, locale } = useI18n();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: ['alerts'], queryFn: async () => (await httpClient.get('/alerts')).data, staleTime: 2 * 60_000, refetchInterval: 5 * 60_000 });
  const markRead = useMutation({
    mutationFn: async () => (await httpClient.post('/alerts/read')).data,
    onSuccess: () => queryClient.setQueryData(['alerts'], (data) => data && ({ ...data, unread: 0, alerts: data.alerts.map((a) => ({ ...a, unread: false })) })),
  });
  const unread = query.data?.unread || 0;
  const number = useMemo(() => new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }), [locale]);
  const money = (value, currency) => { try { return new Intl.NumberFormat(locale, { style: 'currency', currency }).format(value); } catch { return String(value); } };
  const { mutate: markAllRead } = markRead;

  useEffect(() => {
    if (open && unread) {
      const timer = setTimeout(() => markAllRead(), 1500);
      return () => clearTimeout(timer);
    }
    return undefined;
  }, [open, unread, markAllRead]);

  const text = (a) => describeAlert(a, t, number, money);

  return (
    <>
      <button type="button" className="apex-topnav__icon apex-alerts__button" aria-label={unread ? t('alerts.labelUnread', { count: unread }) : t('alerts.label')} aria-expanded={open} onClick={onToggle}>
        <Bell size={17} aria-hidden="true" />
        {unread > 0 && <span className="apex-alerts__badge" aria-hidden="true" dir="ltr">{unread > 9 ? '9+' : unread}</span>}
      </button>
      {open && (
        <div className="apex-topnav__popover apex-alerts" role="dialog" aria-label={t('alerts.label')}>
          <header><strong>{t('alerts.title')}</strong>{query.data?.alerts?.length > 0 && <span className="apex-muted">{t('alerts.count', { count: query.data.alerts.length })}</span>}</header>
          {query.isPending ? <p className="apex-alerts__empty">{t('common.loading')}</p>
            : query.isError ? <p className="apex-alerts__empty">{t('alerts.error')}</p>
              : !query.data.alerts.length ? <p className="apex-alerts__empty"><Info size={15} aria-hidden="true" /> {t('alerts.empty')}</p> : (
                <ul>
                  {query.data.alerts.map((a) => {
                    const Icon = (ICONS[a.kind] || (() => AlertTriangle))(a);
                    return (
                      <li key={a.id}>
                        <button type="button" className={`apex-alerts__item is-${a.severity}${a.unread ? ' is-unread' : ''}`} onClick={() => { onClose(); navigate(a.link); }}>
                          <Icon size={16} aria-hidden="true" />
                          <span>{text(a)}</span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
        </div>
      )}
    </>
  );
}

export default AlertsBell;
