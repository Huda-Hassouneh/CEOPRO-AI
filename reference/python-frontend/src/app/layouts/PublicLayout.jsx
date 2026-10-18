export function PublicLayout({ children, hideHeader = false }) {
  return (
    <div className="public-layout">
      {!hideHeader && (
        <header className="topbar">
          <span className="brand" dir="ltr">KEEL</span>
        </header>
      )}
      <main>{children}</main>
    </div>
  );
}
