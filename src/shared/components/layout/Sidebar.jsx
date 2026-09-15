import { useLocation, useNavigate } from 'react-router-dom';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { useAuthStore } from '../../../features/auth/store/authStore.js';
import { businessPrimaryNavigation, businessSecondaryNavigation } from '../../config/businessNavigation.js';

const isActivePath = (pathname, path) => path && (pathname === path || pathname.startsWith(`${path}/`));

export default function Sidebar({ open = false, onClose }) {
  const { t, dir } = useI18n();
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const clearSession = useAuthStore((state) => state.clearSession);

  const goTo = (item) => {
    if (item.key === 'logout') {
      clearSession();
      navigate('/login', { replace: true });
    } else if (item.path) navigate(item.path);
    onClose?.();
  };

  return (
    <aside className={`business-sidebar${open ? ' is-open' : ''}`} aria-label={t('businessShell.navigation.label')} dir={dir}>
      <div className="business-sidebar__brand">
        <span className="business-sidebar__brand-mark" aria-hidden="true">C</span>
        <span><strong>CEO PRO</strong><small>{t('businessShell.brandSubtitle')}</small></span>
      </div>
      <nav className="business-sidebar__nav" aria-label={t('businessShell.navigation.primary')}>
        {businessPrimaryNavigation.map((item) => {
          const Icon = item.icon;
          const active = isActivePath(pathname, item.path);
          return <button key={item.key} type="button" className={`business-sidebar__item${active ? ' is-active' : ''}`} aria-current={active ? 'page' : undefined} onClick={() => goTo(item)}><Icon size={18} aria-hidden="true" /><span>{t(item.labelKey)}</span></button>;
        })}
      </nav>
      <nav className="business-sidebar__nav business-sidebar__nav--secondary" aria-label={t('businessShell.navigation.secondary')}>
        {businessSecondaryNavigation.map((item) => {
          const Icon = item.icon;
          const active = isActivePath(pathname, item.path);
          return <button key={item.key} type="button" className={`business-sidebar__item${active ? ' is-active' : ''}${item.key === 'logout' ? ' is-danger' : ''}`} aria-current={active ? 'page' : undefined} onClick={() => goTo(item)}><Icon size={18} aria-hidden="true" /><span>{t(item.labelKey)}</span></button>;
        })}
      </nav>
    </aside>
  );
}
