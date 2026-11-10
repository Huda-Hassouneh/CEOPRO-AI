import { useState } from 'react';
import { Mail } from 'lucide-react';
import { useLanding } from '../components/LandingPrimitives.jsx';

// Display order is fixed and intentional.
const team = [
  { name: 'Huda Hassouneh', email: 'huda.hasouneh@gmail.com', tone: 'violet' },
  { name: 'Ghadeer Abdelhadi', email: 'ghadeer.a.abdelhadi@gmail.com', tone: 'mint' },
  { name: 'Noor Hassouneh', email: 'nooor.hassouneh@gmail.com', tone: 'pink' },
  { name: 'Bushra Khawaja', email: 'b.khawaja@gmail.com', tone: 'blue' },
  { name: 'Mahmoud Jamal', email: 'mahmoudjaber11222@gmail.com', tone: 'lilac' },
];

const initials = (name) => name.split(' ').map((part) => part[0]).join('');

export function TeamSection() {
  const { t } = useLanding();
  const [open, setOpen] = useState(null);

  return <section className="lp-section lp-team" id="team"><div className="lp-container">
    <div className="lp-heading lp-heading--center"><p className="lp-eyebrow">{t('team.eyebrow')}</p><h2>{t('team.title')}</h2></div>
    <ul className="lp-team-grid">{team.map(({ name, email, tone }, index) => {
      const expanded = open === index;
      const mailId = `lp-team-mail-${index}`;
      return <li key={email} className={`lp-team-card lp-team-card--${tone}${expanded ? ' is-open' : ''}`}>
        <button type="button" className="lp-team-toggle" aria-expanded={expanded} aria-controls={mailId} onClick={() => setOpen(expanded ? null : index)}>
          <span className="lp-team-avatar" aria-hidden="true"><span dir="ltr">{initials(name)}</span></span>
          <span className="lp-team-name"><bdi>{name}</bdi></span>
          <span className="lp-team-hint">{t('team.hint')}</span>
        </button>
        <div className="lp-team-mail" id={mailId} hidden={!expanded}>
          <a href={`mailto:${email}`}><Mail size={14} aria-hidden="true" /><bdi dir="ltr">{email.split('@')[0]}<wbr />@{email.split('@')[1]}</bdi></a>
        </div>
      </li>;
    })}</ul>
  </div></section>;
}
