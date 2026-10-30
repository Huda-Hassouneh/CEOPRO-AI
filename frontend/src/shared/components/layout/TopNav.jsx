import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { ChevronDown, Command, Languages, LogOut, Menu, Search, X } from 'lucide-react';
import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import httpClient from '../../lib/httpClient.js';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { useAuthStore } from '../../../features/auth/store/authStore.js';
import { getAccountProfile } from '../../utils/accountProfile.js';
import { businessPrimaryNavigation, businessSecondaryNavigation } from '../../config/businessNavigation.js';
import Avatar from '../ui/Avatar.jsx';
import KeelMark from '../brand/KeelMark.jsx';
import ThemeToggle from './ThemeToggle.jsx';
import { signOut } from './signOut.js';
import { PlatformAccessLink } from '../../../features/platform/PlatformAccessLink.jsx';
import { AlertsBell } from '../../../features/alerts/AlertsBell.jsx';
import { WorkspaceSwitcher } from '../../../features/workspaces/components/WorkspaceSwitcher.jsx';

const matchesPath = (pathname, path) => path && (pathname === path || pathname.startsWith(`${path}/`));
const isActive = (pathname, item) => matchesPath(pathname, item.path) || (item.activePaths || []).some((path) => matchesPath(pathname, path));

// Closes a popover on outside click / Escape.
function useDismiss(open, setOpen, ref) {
  useEffect(() => {
    if (!open) return undefined;
    const onPointer = (event) => { if (ref.current && !ref.current.contains(event.target)) setOpen(false); };
    const onKey = (event) => { if (event.key === 'Escape') setOpen(false); };
    document.addEventListener('pointerdown', onPointer);
    document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('pointerdown', onPointer); document.removeEventListener('keydown', onKey); };
  }, [open, setOpen, ref]);
}

function NavTabs({ pathname, t }) {
  const listRef = useRef(null);
  const [indicator, setIndicator] = useState(null);

  // The glass "lens" slides to the active tab.
  const measure = useCallback(() => {
    const list = listRef.current;
    const active = list?.querySelector('[aria-current="page"]');
    if (!list || !active) { setIndicator(null); return; }
    const a = active.getBoundingClientRect();
    const l = list.getBoundingClientRect();
    setIndicator({ left: a.left - l.left + list.scrollLeft, width: a.width });
  }, []);

  useLayoutEffect(() => { measure(); }, [pathname, measure, t]);
  useEffect(() => {
    const list = listRef.current;
    if (!list || typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver(measure);
    observer.observe(list);
    document.fonts?.ready?.then(measure).catch(() => {});
    return () => observer.disconnect();
  }, [measure]);

  return (
    <nav className="apex-topnav__tabs" aria-label={t('businessShell.navigation.primary')}>
      <div className="apex-topnav__tablist" ref={listRef}>
        {indicator && <span className="apex-topnav__lens" style={{ transform: `translateX(${indicator.left}px)`, width: indicator.width }} aria-hidden="true" />}
        {businessPrimaryNavigation.map((item) => {
          const Icon = item.icon;
          const active = isActive(pathname, item);
          return (
            <NavLink key={item.key} to={item.path} className={`apex-topnav__tab${active ? ' is-active' : ''}`} aria-current={active ? 'page' : undefined}>
              <Icon size={16} aria-hidden="true" /><span>{t(item.labelKey)}</span>
            </NavLink>
          );
        })}
      </div>
    </nav>
  );
}

function SearchPalette({ open, onClose, t, dir }) {
  const navigate = useNavigate();
  const inputRef = useRef(null);
  const [query, setQuery] = useState('');
  const [results, setResults] = useState(null);

  useEffect(() => {
    if (!open) { setQuery(''); setResults(null); return undefined; }
    const timer = window.setTimeout(() => inputRef.current?.focus(), 30);
    const onKey = (event) => { if (event.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => { window.clearTimeout(timer); document.removeEventListener('keydown', onKey); };
  }, [open, onClose]);

  // GET /dashboard/search - this company's own products and tracked competitors.
  useEffect(() => {
    const term = query.trim();
    if (!term) { setResults(null); return undefined; }
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      try {
        const response = await httpClient.get('/dashboard/search', { params: { q: term, limit: 6 } });
        if (!cancelled) setResults(response.data);
      } catch {
        if (!cancelled) setResults({ products: [], competitors: [], failed: true });
      }
    }, 220);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [query]);

  if (!open) return null;
  const go = (path) => { onClose(); navigate(path); };
  const term = query.trim().toLowerCase();
  const pages = term ? [...businessPrimaryNavigation, ...businessSecondaryNavigation.filter((i) => i.path)].filter((item) => t(item.labelKey).toLowerCase().includes(term)) : [];
  const hasResults = Boolean(results?.products?.length || results?.competitors?.length || pages.length);

  return (
    <div className="apex-palette" role="dialog" aria-modal="true" aria-label={t('businessShell.search.label')} dir={dir}>
      <button type="button" className="apex-palette__scrim" onClick={onClose} aria-label={t('common.close')} tabIndex={-1} />
      <div className="apex-palette__panel">
        <div className="apex-palette__field">
          <Search size={18} aria-hidden="true" />
          <label className="sr-only" htmlFor="apex-global-search">{t('businessShell.search.label')}</label>
          <input id="apex-global-search" ref={inputRef} value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t('businessShell.search.placeholder')} type="search" autoComplete="off" />
          <kbd>Esc</kbd>
        </div>
        {term && (
          <div className="apex-palette__results" role="listbox" aria-label={t('businessShell.search.label')}>
            {!hasResults && results && <p className="apex-palette__empty">{results.failed ? t('businessShell.search.failed') : t('businessShell.search.noResults')}</p>}
            {pages.length > 0 && <><strong>{t('businessShell.search.pages')}</strong>{pages.map((item) => { const Icon = item.icon; return <button type="button" role="option" aria-selected="false" key={item.key} onClick={() => go(item.path)}><Icon size={15} aria-hidden="true" />{t(item.labelKey)}</button>; })}</>}
            {results?.products?.length > 0 && <><strong>{t('businessShell.search.products')}</strong>{results.products.map((item) => <button type="button" role="option" aria-selected="false" key={item.product_id} onClick={() => go(`/products/${item.product_id}`)}>{item.name}</button>)}</>}
            {results?.competitors?.length > 0 && <><strong>{t('businessShell.search.competitors')}</strong>{results.competitors.map((item) => <button type="button" role="option" aria-selected="false" key={item.global_competitor_id} onClick={() => go(`/market/competitors/${item.global_competitor_id}`)}>{item.name}</button>)}</>}
          </div>
        )}
        {!term && <p className="apex-palette__hint">{t('businessShell.search.hint')}</p>}
      </div>
    </div>
  );
}

export default function TopNav() {
  const { t, dir, locale, setLocale } = useI18n();
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const user = useAuthStore((state) => state.user);
  const clearSession = useAuthStore((state) => state.clearSession);
  const profile = getAccountProfile(user, t);
  const [searchOpen, setSearchOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);
  const profileRef = useRef(null);
  const bellRef = useRef(null);
  useDismiss(profileOpen, setProfileOpen, profileRef);
  useDismiss(notificationsOpen, setNotificationsOpen, bellRef);

  useEffect(() => { setMenuOpen(false); setProfileOpen(false); setNotificationsOpen(false); }, [pathname]);

  // Browser tab title follows the current section: "Products · KEEL".
  useEffect(() => {
    const current = [...businessPrimaryNavigation, ...businessSecondaryNavigation].find((item) => isActive(pathname, item));
    document.title = current ? `${t(current.labelKey)} · KEEL` : 'KEEL';
  }, [pathname, t]);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  // Ctrl/Cmd+K opens search from anywhere.
  useEffect(() => {
    const onKey = (event) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); setSearchOpen(true); }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, []);

  useEffect(() => {
    if (!menuOpen) return undefined;
    const onKey = (event) => { if (event.key === 'Escape') setMenuOpen(false); };
    document.addEventListener('keydown', onKey);
    document.body.style.overflow = 'hidden';
    return () => { document.removeEventListener('keydown', onKey); document.body.style.overflow = ''; };
  }, [menuOpen]);

  const closeSearch = useCallback(() => setSearchOpen(false), []);
  const logout = () => signOut(clearSession, navigate);

  return (
    <>
      <header className={`apex-topnav${scrolled ? ' is-scrolled' : ''}`} dir={dir}>
        <div className="apex-topnav__bar">
          <button type="button" className="apex-topnav__icon apex-topnav__menu" onClick={() => setMenuOpen(true)} aria-label={t('businessShell.mobile.openMenu')} aria-expanded={menuOpen}><Menu size={19} aria-hidden="true" /></button>
          <NavLink to="/dashboard" className="apex-topnav__brand" aria-label="KEEL">
            <span className="apex-topnav__mark" aria-hidden="true"><KeelMark size={20} /></span>
            <span className="apex-topnav__wordmark" dir="ltr">KEEL</span>
          </NavLink>

          <button type="button" className="apex-topnav__search" onClick={() => setSearchOpen(true)} aria-label={t('businessShell.search.open')}>
            <Search size={16} aria-hidden="true" /><span>{t('businessShell.search.placeholder')}</span><kbd aria-hidden="true"><Command size={11} />K</kbd>
          </button>

          <NavTabs pathname={pathname} t={t} />

          <div className="apex-topnav__actions">
            <button type="button" className="apex-topnav__icon apex-topnav__lang" onClick={() => setLocale(locale === 'en' ? 'ar' : 'en')} aria-label={t('common.languageSwitch')}>
              <Languages size={16} aria-hidden="true" /><span>{locale === 'en' ? t('common.arabicShort') : t('common.englishShort')}</span>
            </button>
            <ThemeToggle />
            <div className="apex-topnav__pop" ref={bellRef}>
              <AlertsBell open={notificationsOpen} onToggle={() => setNotificationsOpen((open) => !open)} onClose={() => setNotificationsOpen(false)} />
            </div>
            <div className="apex-topnav__pop" ref={profileRef}>
              <button type="button" className="apex-topnav__profile" aria-label={t('businessShell.profile.label')} aria-haspopup="menu" aria-expanded={profileOpen} onClick={() => setProfileOpen((open) => !open)}>
                <Avatar src={profile.avatarUrl} alt={profile.personName} fallback={profile.initials} size="32px" />
                <ChevronDown size={14} aria-hidden="true" className="apex-topnav__chevron" />
              </button>
              {profileOpen && (
                <div className="apex-topnav__popover apex-topnav__profile-menu" role="menu">
                  <div className="apex-topnav__who"><strong>{profile.personName}</strong><span>{profile.email}</span><span>{profile.companyName}</span></div>
                  <WorkspaceSwitcher onDone={() => setProfileOpen(false)} />
                  {businessSecondaryNavigation.filter((item) => item.path).map((item) => {
                    const Icon = item.icon;
                    return <button key={item.key} type="button" role="menuitem" onClick={() => { setProfileOpen(false); navigate(item.path); }}><Icon size={15} aria-hidden="true" />{t(item.labelKey)}</button>;
                  })}
                  <button type="button" role="menuitem" className="is-danger" onClick={logout}><LogOut size={15} aria-hidden="true" />{t('businessShell.navigation.logout')}</button>
                </div>
              )}
            </div>
          </div>
        </div>
      <PlatformAccessLink />
</header>

      {menuOpen && (
        <div className="apex-sheet" role="dialog" aria-modal="true" aria-label={t('businessShell.navigation.label')} dir={dir}>
          <button type="button" className="apex-sheet__scrim" onClick={() => setMenuOpen(false)} aria-label={t('businessShell.mobile.closeMenu')} tabIndex={-1} />
          <div className="apex-sheet__panel">
            <div className="apex-sheet__head">
              <span className="apex-topnav__brand"><span className="apex-topnav__mark" aria-hidden="true"><KeelMark size={20} /></span><span className="apex-topnav__wordmark" dir="ltr">KEEL</span></span>
              <button type="button" className="apex-topnav__icon" onClick={() => setMenuOpen(false)} aria-label={t('businessShell.mobile.closeMenu')}><X size={18} aria-hidden="true" /></button>
            </div>
            <nav className="apex-sheet__grid" aria-label={t('businessShell.navigation.primary')}>
              {businessPrimaryNavigation.map((item, index) => {
                const Icon = item.icon;
                const active = isActive(pathname, item);
                return <NavLink key={item.key} to={item.path} className={`apex-sheet__item${active ? ' is-active' : ''}`} aria-current={active ? 'page' : undefined} style={{ '--i': index }} onClick={() => setMenuOpen(false)}><Icon size={20} aria-hidden="true" /><span>{t(item.labelKey)}</span></NavLink>;
              })}
            </nav>
            <nav className="apex-sheet__secondary" aria-label={t('businessShell.navigation.secondary')}>
              {businessSecondaryNavigation.filter((item) => item.path).map((item) => { const Icon = item.icon; return <NavLink key={item.key} to={item.path} onClick={() => setMenuOpen(false)}><Icon size={16} aria-hidden="true" />{t(item.labelKey)}</NavLink>; })}
              <WorkspaceSwitcher onDone={() => setMenuOpen(false)} />
              <button type="button" className="is-danger" onClick={logout}><LogOut size={16} aria-hidden="true" />{t('businessShell.navigation.logout')}</button>
            </nav>
          </div>
        </div>
      )}

      <SearchPalette open={searchOpen} onClose={closeSearch} t={t} dir={dir} />
    </>
  );
}
