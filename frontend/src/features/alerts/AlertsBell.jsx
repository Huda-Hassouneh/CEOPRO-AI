import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, Bell, Info, PackageX, Radar, Tag, TrendingDown, TrendingUp, CreditCard, FileWarning, Gauge } from 'lucide-react';
import { useI18n } from '../../app/providers/I18nProvider.jsx';
import httpClient from '../../shared/lib/httpClient.js';
import { AlertsLoadError } from './AlertsLoadError.jsx';

export const ICONS = {
  competitor_price: (a) => (a.params.change_pct < 0 ? TrendingDown : TrendingUp),
  restock: () => PackageX, competitor_comments_negative: () => AlertTriangle, price_gap: () => Tag, new_competitors: () => Radar,
  import_failed: () => FileWarning, payment_failed: () => CreditCard, trial_ending: () => CreditCard,
  credits_low: () => Gauge, credits_exhausted: () => Gauge,
};

// One alert in words (the bell and the dashboard's recent updates).
export function describeAlert(a, t, number, money) {
  const p = a.params;
  switch (a.kind) {
    case 'competitor_price': return t(`alerts.competitor_price.${p.change_pct < 0 ? 'down' : 'up'}`, { competitor: p.competitor, product: p.product, price: money(p.price, p.currency), pct: number.format(Math.abs(p.change_pct)) });
    case 'competitor_comments_negative': return t('alerts.competitor_comments_negative', { competitor: p.competitor, pct: number.format(p.negative_pct ?? 0), count: number.format(p.count ?? 0) });
    case 'restock': return t('alerts.restock', { product: p.product, days: number.format(p.days ?? 0), quantity: number.format(p.quantity ?? 0) });
    case 'price_gap': return t(`alerts.price_gap.${p.gap_pct > 0 ? 'above' : 'below'}`, { product: p.product, pct: number.format(Math.abs(p.gap_pct)), competitor: p.competitor });
    case 'new_competitors': return t('alerts.new_competitors', { count: p.count, tracked: p.tracked });
    case 'import_failed': return t('alerts.import_failed', { name: p.name || '' });
    case 'trial_ending': return t('alerts.trial_ending', { days: p.days });
    case 'payment_failed': return t('alerts.payment_failed');
    case 'credits_low':
    case 'credits_exhausted': return t(`alerts.${a.kind}`, { budget: t(`alerts.budget.${p.budget === 'ai' ? 'ai' : 'data'}`), percent: number.format(p.percent ?? 0), date: p.resets_on || '' });
    default: return a.kind;
  }
}

// The top bar's alerts: what needs attention now, from live data (/alerts).
export function AlertsBell({ open, onToggle, onClose }) {
  const { t, locale } = useI18n();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [section, setSection] = useState('inbox');
  const [includeDismissed, setIncludeDismissed] = useState(false);
  const [olderNotifications, setOlderNotifications] = useState([]);
  const [nextCursor, setNextCursor] = useState(null);
  const [actionError, setActionError] = useState(false);
  const [morePending, setMorePending] = useState(false);
  const query = useQuery({ queryKey: ['alerts'], queryFn: async () => (await httpClient.get('/alerts')).data, staleTime: 2 * 60_000, refetchInterval: 5 * 60_000, retry: false });
  const notificationsQuery = useQuery({
    queryKey: ['notifications', includeDismissed],
    queryFn: async () => (await httpClient.get('/notifications', { params: { limit: 20, include_dismissed: includeDismissed } })).data,
    staleTime: 30_000, refetchInterval: 5 * 60_000, retry: false,
  });
  const markRead = useMutation({
    mutationFn: async () => (await httpClient.post('/alerts/read')).data,
    onSuccess: () => queryClient.setQueryData(['alerts'], (data) => data && ({ ...data, unread: 0, alerts: data.alerts.map((a) => ({ ...a, unread: false })) })),
  });
  const markOneRead = useMutation({
    mutationFn: async (id) => (await httpClient.post(`/notifications/${id}/read`)).data,
    onSuccess: () => { setActionError(false); queryClient.invalidateQueries({ queryKey: ['notifications'] }); },
    onError: () => setActionError(true),
  });
  const markAllNotificationsRead = useMutation({
    mutationFn: async () => (await httpClient.post('/notifications/read-all')).data,
    onSuccess: () => { setActionError(false); queryClient.invalidateQueries({ queryKey: ['notifications'] }); },
    onError: () => setActionError(true),
  });
  const dismissNotification = useMutation({
    mutationFn: async (id) => (await httpClient.post(`/notifications/${id}/dismiss`)).data,
    onSuccess: () => { setActionError(false); queryClient.invalidateQueries({ queryKey: ['notifications'] }); },
    onError: () => setActionError(true),
  });
  const unreadAlerts = query.data?.unread || 0;
  const unread = unreadAlerts + (notificationsQuery.data?.unread_count || 0);
  const number = useMemo(() => new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }), [locale]);
  const money = (value, currency) => { try { return new Intl.NumberFormat(locale, { style: 'currency', currency }).format(value); } catch { return String(value); } };
  const { mutate: markAllRead } = markRead;

  useEffect(() => {
    if (open && section === 'alerts' && unreadAlerts) {
      const timer = setTimeout(() => markAllRead(), 1500);
      return () => clearTimeout(timer);
    }
    return undefined;
  }, [open, section, unreadAlerts, markAllRead]);

  useEffect(() => { setOlderNotifications([]); setNextCursor(notificationsQuery.data?.next_cursor || null); }, [includeDismissed, notificationsQuery.data?.next_cursor]);

  const text = (a) => describeAlert(a, t, number, money);

  return (
    <>
      <button type="button" className="apex-topnav__icon apex-alerts__button" aria-label={unread ? t('alerts.labelUnread', { count: unread }) : t('alerts.label')} aria-expanded={open} onClick={onToggle}>
        <Bell size={17} aria-hidden="true" />
        {unread > 0 && <span className="apex-alerts__badge" aria-hidden="true" dir="ltr">{unread > 9 ? '9+' : unread}</span>}
      </button>
      {open && (
        <div className="apex-topnav__popover apex-alerts" role="dialog" aria-label={t('alerts.label')}>
          <header><strong>{t('alerts.title')}</strong><span className="apex-muted">{section === 'inbox' ? t('alerts.count', { count: notificationsQuery.data?.total || 0 }) : t('alerts.count', { count: query.data?.alerts?.length || 0 })}</span></header>
          <nav className="apex-alerts__tabs" aria-label={t('alerts.title')}>
            <button type="button" aria-pressed={section === 'inbox'} onClick={() => setSection('inbox')}>{t('alerts.inboxTab')}</button>
            <button type="button" aria-pressed={section === 'alerts'} onClick={() => setSection('alerts')}>{t('alerts.smartTab')}</button>
          </nav>
          {section === 'inbox' ? <>
            {actionError && <p className="apex-alerts__action-error" role="alert">{t('alerts.actionFailed')}</p>}
            <div className="apex-alerts__actions">
              <button type="button" className="apex-btn apex-btn--ghost apex-btn--sm" onClick={() => { setIncludeDismissed((value) => !value); setOlderNotifications([]); }}>
                {t(includeDismissed ? 'alerts.hideHistory' : 'alerts.showHistory')}
              </button>
              {(notificationsQuery.data?.unread_count || 0) > 0 && <button type="button" className="apex-btn apex-btn--ghost apex-btn--sm" disabled={markAllNotificationsRead.isPending} onClick={() => markAllNotificationsRead.mutate()}>{t('alerts.markAllRead')}</button>}
            </div>
            {notificationsQuery.isPending ? <p className="apex-alerts__empty">{t('common.loading')}</p>
              : notificationsQuery.isError ? <AlertsLoadError onRetry={() => notificationsQuery.refetch()} busy={notificationsQuery.isFetching} t={t} />
                : !(notificationsQuery.data?.items?.length || olderNotifications.length) ? <p className="apex-alerts__empty"><Info size={15} aria-hidden="true" /> {t('alerts.inboxEmpty')}</p> : <>
                  <ul>
                    {[...(notificationsQuery.data?.items || []), ...olderNotifications].map((item) => {
                      const alert = { kind: item.event_kind, params: item.payload?.params || {} };
                      const Icon = (ICONS[item.event_kind] || (() => AlertTriangle))(alert);
                      return <li key={item.notification_id}>
                        <div className={`apex-alerts__item is-${item.severity}${item.read_at ? '' : ' is-unread'}${item.dismissed_at ? ' is-dismissed' : ''}`}>
                            <button type="button" className="apex-alerts__notification-open" onClick={async () => { if (!item.read_at) { try { await markOneRead.mutateAsync(item.notification_id); } catch { return; } } onClose(); navigate(item.payload?.link || '/'); }}>
                            <Icon size={16} aria-hidden="true" />
                            <span>{text(alert)}<time dateTime={item.created_at}>{new Date(item.created_at).toLocaleString(locale)}</time></span>
                          </button>
                          {!item.dismissed_at && <button type="button" className="apex-alerts__dismiss" aria-label={t('alerts.dismiss')} onClick={() => dismissNotification.mutate(item.notification_id)}>{t('alerts.dismiss')}</button>}
                        </div>
                      </li>;
                    })}
                  </ul>
                  {nextCursor && <button type="button" className="apex-btn apex-btn--ghost apex-btn--sm apex-alerts__more" disabled={morePending} onClick={async () => {
                    setMorePending(true);
                    setActionError(false);
                    try {
                      const response = await httpClient.get('/notifications', { params: { limit: 20, include_dismissed: includeDismissed, before_created_at: nextCursor.created_at, before_notification_id: nextCursor.notification_id } });
                      setOlderNotifications((current) => [...current, ...response.data.items]);
                      setNextCursor(response.data.next_cursor);
                    } catch {
                      setActionError(true);
                    } finally {
                      setMorePending(false);
                    }
                  }}>{morePending ? t('common.loading') : t('alerts.loadMore')}</button>}
                </>}
          </> : query.isPending ? <p className="apex-alerts__empty">{t('common.loading')}</p>
            : query.isError ? <AlertsLoadError onRetry={() => query.refetch()} busy={query.isFetching} t={t} />
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
