import { Link } from 'react-router-dom';
import { useI18n } from '../../app/providers/I18nProvider.jsx';
import { PUBLIC_POLICIES, policyCopy } from './policyCatalog.js';
import './styles/Legal.css';
export function PolicyLinks({ billing = false }) {
  const { locale } = useI18n();
  const lang = locale === 'ar' ? 'ar' : 'en';
  return <div className="policy-links"><nav aria-label={policyCopy[lang].navigation}>
    {PUBLIC_POLICIES.map(policy => <Link key={policy.kind} to={policy.path} target={billing ? '_blank' : undefined} rel={billing ? 'noopener noreferrer' : undefined}>{policy[lang]}</Link>)}
  </nav><small>{billing ? policyCopy[lang].linksNotice : policyCopy[lang].draft}</small></div>;
}
