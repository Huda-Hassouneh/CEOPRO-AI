import KeelLogo from '../../shared/components/branding/KeelLogo.jsx';
export function PublicLayout({ children, hideHeader = false }) {
  return (
    <div className="public-layout">
      {!hideHeader && (
        <header className="topbar">
          <KeelLogo size={30} />
        </header>
      )}
      <main>{children}</main>
    </div>
  );
}
