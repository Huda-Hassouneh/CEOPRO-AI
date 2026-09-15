export default function PageHeader({ title, subtitle, actions, children, className = '' }) {
  return <div className={`business-page-header ${className}`.trim()}><div className="business-page-header__copy">{title && <h1>{title}</h1>}{subtitle && <p>{subtitle}</p>}</div>{(actions || children) && <div className="business-page-header__actions">{actions || children}</div>}</div>;
}
