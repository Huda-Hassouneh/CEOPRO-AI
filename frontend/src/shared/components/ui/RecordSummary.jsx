import Card from './Card.jsx';
import './RecordSummary.css';

/** Display real values with an explicit label and scope. */
export default function RecordSummary({ items }) {
  return <div className="record-summary">{items.map(({ label, value, hint, icon }) =>
    <Card className="record-summary__item" key={label}>
      <div className="record-summary__copy"><dl><dt>{label}</dt><dd>{value ?? '—'}</dd></dl>{hint && <p>{hint}</p>}</div>
      {icon && <span className="record-summary__icon" aria-hidden="true">{icon}</span>}
    </Card>
  )}</div>;
}
