import { useEffect, useRef, useState } from 'react';
import { Globe2, Menu, X } from 'lucide-react';
import { Link } from 'react-router-dom';
import { routePaths } from '../../../app/router/routePaths.js';
import { Brand, useLanding } from './LandingPrimitives.jsx';

const navLinks = [['hero', 'home'], ['features', 'features'], ['models', 'models'], ['how-it-works', 'workflow'], ['pricing', 'pricing'], ['about', 'about']];

export function LocaleToggle() {
  const { locale, setLocale, t } = useLanding();
  return <button type="button" className="lp-locale" onClick={() => setLocale(locale === 'en' ? 'ar' : 'en')} aria-label={t('nav.language')}><Globe2 size={16} aria-hidden="true" /><span lang={locale === 'en' ? 'ar' : 'en'}>{locale === 'en' ? 'العربية' : 'English'}</span></button>;
}

export function LandingNavbar() {
  const { t } = useLanding();
  const [open, setOpen] = useState(false);
  const toggle = useRef(null);
  const header = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const closeOnEscape = (event) => { if (event.key === 'Escape') { setOpen(false); toggle.current?.focus(); } };
    const closeOutside = (event) => { if (!header.current?.contains(event.target)) setOpen(false); };
    document.addEventListener('keydown', closeOnEscape);
    document.addEventListener('pointerdown', closeOutside);
    return () => { document.removeEventListener('keydown', closeOnEscape); document.removeEventListener('pointerdown', closeOutside); };
  }, [open]);
  return <header className="lp-navbar" ref={header}>
    <div className="lp-container lp-navbar-inner"><Brand />
      <nav className={`lp-nav-links ${open ? 'is-open' : ''}`} id="landing-navigation" aria-label={t('nav.label')} onClick={(event) => { if (event.target.closest('a')) setOpen(false); }}>
        {navLinks.map(([id, key]) => <a key={id} href={`#${id}`}>{t(`nav.${key}`)}</a>)}
        <div className="lp-mobile-account"><Link to={routePaths.login}>{t('nav.login')}</Link><Link className="lp-nav-cta" to={routePaths.welcome}>{t('nav.start')}</Link></div>
      </nav>
      <div className="lp-nav-actions"><LocaleToggle /><Link className="lp-desktop-account" to={routePaths.login}>{t('nav.login')}</Link><Link className="lp-nav-cta lp-desktop-account" to={routePaths.welcome}>{t('nav.start')}</Link><button ref={toggle} type="button" className="lp-menu-toggle" aria-controls="landing-navigation" aria-expanded={open} aria-label={t(open ? 'nav.close' : 'nav.menu')} onClick={() => setOpen(!open)}>{open ? <X size={23} /> : <Menu size={23} />}</button></div>
    </div>
  </header>;
}

export function LandingFooter() {
  const { t, n } = useLanding();
  return <footer className="lp-footer"><div className="lp-container"><div className="lp-footer-grid"><div><Brand /><p>{t('footer.description')}</p><LocaleToggle /></div><div><h2>{t('footer.product')}</h2>{navLinks.slice(1, 5).map(([id, key]) => <a key={id} href={`#${id}`}>{t(`nav.${key}`)}</a>)}</div><div><h2>{t('footer.company')}</h2><a href="#about">{t('nav.about')}</a><a href="#how-it-works">{t('nav.workflow')}</a></div><div><h2>{t('footer.account')}</h2><Link to={routePaths.login}>{t('nav.login')}</Link><Link to={routePaths.welcome}>{t('nav.start')}</Link></div></div><div className="lp-footer-bottom"><span>{t('footer.rights', { year: n(new Date().getFullYear()).replace(/[,٬]/g, '') })}</span><span>{t('footer.note')}</span></div></div></footer>;
}
