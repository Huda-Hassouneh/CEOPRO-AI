import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { UI_TESTING_MODE } from "../../config/uiTestingMode.js";
import { router } from "../../../app/router/index.jsx";

const destinations = [
  ["interfaceCopy.dashboard", "/dashboard"],
  ["interfaceCopy.market", "/market"],
  ["interfaceCopy.forecasts", "/demand"],
  ["interfaceCopy.aiAdvisor", "/ai-advisor"],
  ["interfaceCopy.data", "/connect-data"],
  ["interfaceCopy.billing", "/billing"],
  ["interfaceCopy.plans", "/billing/plans"],
  ["interfaceCopy.admin", "/admin"],
  ["interfaceCopy.adminBilling", "/admin/billing"],
  ["interfaceCopy.onboarding", "/onboarding/plan"],
];

/** Explicitly labelled local-only UI inspection: no authentication is implied. */
export function UiTestingToolbar() {
  const { t: copyT } = useI18n();
  if (!UI_TESTING_MODE) return null;
  return (
    <nav aria-label={copyT("interfaceCopy.developmentUiPreviewNavigation")} style={{
      position: "fixed", bottom: 8, right: 8, left: 8, zIndex: 9999,
      display: "flex", alignItems: "center", flexWrap: "wrap", gap: 8,
      padding: "9px 12px", borderRadius: 12,
      background: "#132138", color: "#fff", boxShadow: "0 6px 24px #0004",
      font: "12px/1.5 system-ui, sans-serif",
    }}>
      <strong style={{ marginRight: 6 }}>{copyT("interfaceCopy.uiTestingFictionalSampleDataNoAuthenticationNoBackendWrites")}</strong>
      {destinations.map(([label, url]) => (
        <button key={url} type="button" onClick={() => router.navigate(url)} style={{
          padding: 0, border: 0, background: "none", color: "#bfe3ff",
          textDecoration: "underline", cursor: "pointer", font: "inherit",
        }}>{copyT(label)}</button>
      ))}
    </nav>
  );
}
