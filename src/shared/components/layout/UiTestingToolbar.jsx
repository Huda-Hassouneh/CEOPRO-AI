import { UI_TESTING_MODE } from "../../config/uiTestingMode.js";
import { router } from "../../../app/router/index.jsx";

const destinations = [
  ["Dashboard", "/dashboard"],
  ["Market", "/market"],
  ["Forecasts", "/demand"],
  ["AI Advisor", "/ai-advisor"],
  ["Data", "/connect-data"],
  ["Billing", "/billing"],
  ["Plans", "/billing/plans"],
  ["Admin", "/admin"],
  ["Admin billing", "/admin/billing"],
  ["Onboarding", "/onboarding/plan"],
];

/** Explicitly labelled local-only UI inspection: no authentication is implied. */
export function UiTestingToolbar() {
  if (!UI_TESTING_MODE) return null;
  return (
    <nav aria-label="Development UI preview navigation" style={{
      position: "fixed", bottom: 8, right: 8, left: 8, zIndex: 9999,
      display: "flex", alignItems: "center", flexWrap: "wrap", gap: 8,
      padding: "9px 12px", borderRadius: 12,
      background: "#132138", color: "#fff", boxShadow: "0 6px 24px #0004",
      font: "12px/1.5 system-ui, sans-serif",
    }}>
      <strong style={{ marginRight: 6 }}>UI TESTING · FICTIONAL SAMPLE DATA · no authentication · no backend writes</strong>
      {destinations.map(([label, url]) => (
        <button key={url} type="button" onClick={() => router.navigate(url)} style={{
          padding: 0, border: 0, background: "none", color: "#bfe3ff",
          textDecoration: "underline", cursor: "pointer", font: "inherit",
        }}>{label}</button>
      ))}
    </nav>
  );
}
