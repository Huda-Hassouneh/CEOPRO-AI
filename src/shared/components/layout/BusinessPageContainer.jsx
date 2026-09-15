export default function BusinessPageContainer({ children, className = '', wide = false }) {
  return <div className={`business-page-container${wide ? ' is-wide' : ''} ${className}`.trim()}>{children}</div>;
}
