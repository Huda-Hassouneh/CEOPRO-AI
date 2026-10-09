import symbol from '../../../assets/images/keel-symbol.png';
import './KeelLogo.css';

export default function KeelLogo({ size = 36, iconOnly = false, className = '' }) {
  return (
    <span className={`keel-logo ${className}`.trim()} dir="ltr" role="img" aria-label="KEEL" style={{ '--keel-logo-size': `${size}px` }}>
      <span className="keel-logo__symbol" aria-hidden="true">
        <img src={symbol} alt="" />
      </span>
      {!iconOnly && <span className="keel-logo__wordmark" aria-hidden="true">KEEL</span>}
    </span>
  );
}
