import { NavLink } from "react-router-dom";
import { routePaths } from "../../../app/router/routePaths.js";

export function DemandPredictionTabs({ t, inventoryAllowed = false }) {
  const tabs = [
    ["demand.tabs.overview", routePaths.forecasts, true],
    ["demand.tabs.products", routePaths.forecastProducts, false],
    ...(inventoryAllowed ? [["demand.tabs.inventory", routePaths.forecastInventory, false]] : []),
    ["demandApproved.evaluation.title", routePaths.forecastAccuracy, false]
  ];

  return (
    <nav className="demand-tabs" aria-label={t("demand.tabs.label")}>
      {tabs.map(([labelKey, to, end]) => (
        <NavLink key={to} to={to} end={end}>
          {t(labelKey)}
        </NavLink>
      ))}
    </nav>
  );
}
