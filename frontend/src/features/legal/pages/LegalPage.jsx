import { useEffect } from 'react';
import { Link } from 'react-router-dom';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { usePlans } from '../../billing/hooks/usePlans.js';
import { formatMoney } from '../../billing/utils/money.js';
import { PolicyLinks } from '../PolicyLinks.jsx';
import { PUBLIC_POLICIES, POLICY_CANDIDATE_VERSION, parsePolicyMarkdown, policyCopy } from '../policyCatalog.js';
import '../styles/Legal.css';

const documents = import.meta.glob('../content/*/*.md', { query: '?raw', import: 'default', eager: true });
const EMAIL = 'keel.business.ai@gmail.com';
function InlineText({ text, unresolved }) {
  return text.split(/(\[\[[A-Z0-9_]+\]\]|\*\*[^*]+\*\*|https:\/\/[^\s]+|keel\.business\.ai@gmail\.com)/g).map((part, index) => {
    if (part.startsWith('[[')) return <mark key={index} title={unresolved}><bdi>{part}</bdi></mark>;
    if (part.startsWith('**')) return <strong key={index}><InlineText text={part.slice(2, -2)} unresolved={unresolved} /></strong>;
    if (part.startsWith('https://')) return <a key={index} href={part} target="_blank" rel="noopener noreferrer"><bdi>{part}</bdi></a>;
    if (part === EMAIL) return <a key={index} href={`mailto:${EMAIL}`}><bdi>{EMAIL}</bdi></a>;
    return part;
  });
}
function CatalogTerms({ copy, locale }) {
  const query = usePlans();
  const mismatched = query.isSuccess && ['starter', 'growth', 'enterprise'].some(key => query.data.plans.find(plan => plan.id === key)?.trialDays !== 14);
  return <section aria-labelledby="policy-catalog-title"><h2 id="policy-catalog-title">{copy.catalogTitle}</h2><p>{copy.catalogNote}</p><p>{copy.trialPolicy}</p>
    {query.isPending ? <p role="status">…</p> : query.isError ? <p role="alert">{copy.unavailable}</p> : <div className="policy-table-scroll"><table>
      <thead><tr><th scope="col">{copy.plan}</th><th scope="col">{copy.period}</th><th scope="col">{copy.amount}</th><th scope="col">{copy.days}</th></tr></thead>
      <tbody>{query.data.plans.flatMap(plan => Object.entries(plan.prices || {}).map(([period, price]) => <tr key={`${plan.id}:${period}`}><th scope="row">{plan.name?.[locale] || plan.name?.en}</th><td>{copy.periods[period] || <bdi>{period}</bdi>}</td><td><bdi>{formatMoney(price.amount, price.currency, locale)}</bdi></td><td>{plan.trialDays}</td></tr>))}</tbody>
    </table></div>}
    {mismatched && <p className="policy-review-note" role="status">{copy.discrepancy}</p>}
  </section>;
}
export function LegalPage({ kind }) {
  const { locale, dir, setLocale } = useI18n();
  const lang = locale === 'ar' ? 'ar' : 'en';
  const copy = policyCopy[lang];
  const policy = PUBLIC_POLICIES.find(value => value.kind === kind);
  const blocks = parsePolicyMarkdown(documents[`../content/${lang}/${kind}.md`] || '');
  useEffect(() => {
    const oldTitle = document.title;
    const existing = document.querySelector('meta[name="robots"]');
    const oldValue = existing?.content;
    const robots = existing || document.createElement('meta');
    robots.name = 'robots'; robots.content = 'noindex, nofollow';
    if (!existing) document.head.appendChild(robots);
    document.title = `${policy[lang]} — KEEL — DRAFT`;
    return () => { document.title = oldTitle; if (existing) robots.content = oldValue; else robots.remove(); };
  }, [lang, policy]);
  return <main className="legal-page" dir={dir} lang={lang}><article className="legal-page__card">
    <header className="policy-page-header"><Link className="legal-page__back" to="/">KEEL</Link><button type="button" onClick={() => setLocale(lang === 'en' ? 'ar' : 'en')}>{copy.language}</button></header>
    <h1>{policy[lang]}</h1>
    <aside className="policy-draft-banner" role="note"><strong>{copy.draft}</strong><p>{copy.notice}</p><p>{copy.version}: <bdi>{POLICY_CANDIDATE_VERSION}</bdi></p></aside>
    <PolicyLinks />
    {kind === 'contact' ? <section><h2>KEEL</h2><p>{copy.contactIntro}</p><p>{copy.operator}</p><p>{copy.email}: <a href={`mailto:${EMAIL}`}><bdi>{EMAIL}</bdi></a></p><p className="policy-review-note">{copy.missing}</p><p>{copy.provider} <a href="https://paddle.net" target="_blank" rel="noopener noreferrer"><bdi>paddle.net</bdi></a></p></section> : <>
      <section><h2>{copy.intentions}</h2><ul>{copy.rules.map(rule => <li key={rule}>{rule}</li>)}</ul></section>
      {(kind === 'subscriptions' || kind === 'trial') && <CatalogTerms copy={copy} locale={lang} />}
      <div className="policy-draft-body">{blocks.map((block, index) => {
        const body = <InlineText text={block.body} unresolved={copy.unresolved} />;
        if (block.type === 'section') return <section key={index}><h2>{block.heading}</h2>{block.body.startsWith('- ') ? <ul>{block.body.split('\n').map((line, item) => <li key={item}><InlineText text={line.replace(/^- /, '')} unresolved={copy.unresolved} /></li>)}</ul> : <p>{body}</p>}</section>;
        if (block.type === 'list') return <ul key={index}>{block.body.split('\n').map((line, item) => <li key={item}><InlineText text={line.replace(/^- /, '')} unresolved={copy.unresolved} /></li>)}</ul>;
        return <p key={index} className={block.type === 'note' ? 'policy-review-note' : undefined}>{body}</p>;
      })}</div>
    </>}
    <footer><PolicyLinks /></footer>
  </article></main>;
}
export default LegalPage;
