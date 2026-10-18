import { Link } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { routePaths } from '../../../app/router/routePaths.js';
import { LEGAL_LAST_UPDATED, legalContent } from '../legalContent.js';
import '../styles/Legal.css';

const CONTACT_EMAIL = import.meta.env.VITE_SUPPORT_EMAIL || '';

export function LegalPage({ kind }) {
  const { locale, dir, t } = useI18n();
  const content = legalContent[kind][locale === 'ar' ? 'ar' : 'en'];
  const updated = new Intl.DateTimeFormat(locale, { dateStyle: 'long' }).format(new Date(`${LEGAL_LAST_UPDATED}T12:00:00Z`));
  const other = kind === 'terms' ? 'privacy' : 'terms';
  return (
    <main className="legal-page" dir={dir}>
      <article className="legal-page__card">
        <Link className="legal-page__back" to={routePaths.landing}><ArrowLeft size={15} aria-hidden="true" />KEEL</Link>
        <h1>{content.title}</h1>
        <p className="legal-page__updated">{t('legal.updated', { date: updated })}</p>
        <p className="legal-page__intro">{content.intro}</p>
        {content.sections.map(([heading, body]) => (
          <section key={heading}>
            <h2>{heading}</h2>
            <p>{body}</p>
          </section>
        ))}
        {CONTACT_EMAIL && <p className="legal-page__contact">{t('legal.contact')} <a href={`mailto:${CONTACT_EMAIL}`} dir="ltr">{CONTACT_EMAIL}</a></p>}
        <Link className="legal-page__other" to={routePaths[other]}>{legalContent[other][locale === 'ar' ? 'ar' : 'en'].title}</Link>
      </article>
    </main>
  );
}

export default LegalPage;
