export function ComingSoonOverlay({
  children,
  text = "Coming Soon",
  isActive = true
}) {
  // If the feature is active, just render the normal content
  if (!isActive) return <>{children}</>;

  return (
    <div
      style={{
        position: "relative",
        overflow: "hidden",
        width: "100%",
        height: "100%"
      }}
    >
      {/* Centered Overlay Label */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          zIndex: 50,
          display: "flex",
          alignItems: "center",
          justifyContent: "center"
        }}
      >
        <span
          style={{
            backgroundColor: "var(--bg-primary, #ffffff)",
            color: "var(--text-primary, #111827)",
            padding: "0.5rem 1.25rem",
            borderRadius: "9999px",
            fontWeight: "600",
            fontSize: "0.875rem",
            boxShadow:
              "0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05)",
            border: "1px solid var(--border-color, #e5e7eb)"
          }}
        >
          {text}
        </span>
      </div>

      {/* Blurred & Disabled Content */}
      <div
        style={{
          pointerEvents: "none",
          userSelect: "none",
          opacity: 0.6,
          filter: "blur(5px) grayscale(20%)"
        }}
      >
        {children}
      </div>
    </div>
  );
}
