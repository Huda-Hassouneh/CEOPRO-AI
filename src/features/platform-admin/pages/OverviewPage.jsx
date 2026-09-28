import { Link } from "react-router-dom";
import {
  Building2,
  Users,
  CreditCard,
  Clock3,
  ArrowUpRight,
  AlertCircle,
  Search
} from "lucide-react";
import { useAdminQuery, useAdminText } from "../components/AdminContext.jsx";
import { Panel, Identity, Button } from "../components/AdminUI.jsx";
import Skeleton from "../../../shared/components/ui/Skeleton.jsx";
import { en as adminEn, ar as adminAr } from "../locales/messages.js";

export function OverviewPage() {
  const query = useAdminQuery("overview"),
    { t: adminText, locale } = useAdminText(),
    data = query.data;
  // Fall back to the existing locale messages if the shared lookup returns a key.
  const t = (key, values = {}) => {
    const translated = adminText(key, values);
    if (translated !== key && translated !== `platformAdmin.${key}`)
      return translated;
    const message = (locale === "ar" ? adminAr : adminEn)[key] ?? adminEn[key];
    if (typeof message !== "string") return key;
    return message.replace(/\{\{(\w+)\}\}/g, (match, name) =>
      values[name] == null ? match : String(values[name])
    );
  };
  const dateLabel = (value, time = false) =>
    !value || Number.isNaN(Date.parse(value)) ? (
      t("unknown")
    ) : (
      <bdi>
        {new Intl.DateTimeFormat(locale, {
          dateStyle: "medium",
          ...(time ? { timeStyle: "short" } : {})
        }).format(new Date(value))}
      </bdi>
    );
  const planLabel = (name, id) => {
    const value = name || id;
    return ["standard", "pro", "custom"].includes(value)
      ? t(value)
      : value || t("unknown");
  };
  const actionLabel = (action) => {
    if (!action) return t("unknown");
    const translated = t(action);
    return translated === action || translated === `platformAdmin.${action}`
      ? String(action)
          .replace(/([a-z\d])([A-Z])/g, "$1 $2")
          .replace(/[_-]+/g, " ")
      : translated;
  };
  return (
    <>
      <header className="pa-heading">
        <div>
          <span className="pa-eyebrow">{t("platformScope")}</span>
          <h1>{t("overview")}</h1>
          <p>{t("overviewDescription")}</p>
        </div>
      </header>
      {query.isPending ? (
        <div role="status" aria-label={t("loading")} className="pa-loading">
          <Skeleton height="90px" />
          <Skeleton height="280px" />
        </div>
      ) : query.isError ? (
        <div className="pa-empty" role="alert">
          <AlertCircle size={30} />
          <h2>{t(query.error?.code === "notFound" ? "notFound" : "error")}</h2>
          <Button onClick={() => query.refetch()}>{t("retry")}</Button>
        </div>
      ) : (
        data && (
          <>
            <div className="pa-kpis">
              {[
                ["totalCompanies", data.companies, Building2, "companies"],
                ["totalUsers", data.users, Users, "users"],
                [
                  "activeSubscriptions",
                  data.active,
                  CreditCard,
                  "billing?tab=subscriptions"
                ],
                [
                  "activeTrials",
                  data.trials,
                  Clock3,
                  "billing?tab=subscriptions"
                ]
              ].map(([key, value, Icon, path]) => (
                <Link className="pa-kpi" key={key} to={`/admin/${path}`}>
                  <div>
                    <span className="pa-kpi-icon">
                      <Icon size={21} />
                    </span>
                    <ArrowUpRight size={16} />
                  </div>
                  <span>{t(key)}</span>
                  <strong>{new Intl.NumberFormat(locale).format(value)}</strong>
                </Link>
              ))}
            </div>
            <div className="pa-overview-charts">
              <Panel
                title={t("growth")}
                actions={<span className="pa-muted">{t("growthNote")}</span>}
              >
                <div className="pa-chart-legend">
                  <span>
                    <i />
                    {t("companies")}
                  </span>
                  <span>
                    <i />
                    {t("users")}
                  </span>
                </div>
                <div
                  className="pa-bar-chart"
                  role="img"
                  aria-label={data.growth
                    .map((g) => t("chartSummary", { ...g }))
                    .join(" ")}
                >
                  {data.growth.map((g) => (
                    <div className="pa-bar-group" key={g.month}>
                      <div className="pa-bars">
                        <div
                          style={{
                            height: `${Math.max(3, (g.companies / Math.max(1, ...data.growth.map((r) => Math.max(r.companies, r.users)))) * 160)}px`
                          }}
                        >
                          <b>{g.companies}</b>
                        </div>
                        <div
                          style={{
                            height: `${Math.max(3, (g.users / Math.max(1, ...data.growth.map((r) => Math.max(r.companies, r.users)))) * 160)}px`
                          }}
                        >
                          <b>{g.users}</b>
                        </div>
                      </div>
                      <span>
                        {new Intl.DateTimeFormat(locale, {
                          month: "short"
                        }).format(new Date(`${g.month}-01T12:00:00Z`))}
                      </span>
                    </div>
                  ))}
                </div>
              </Panel>
              <Panel title={t("distribution")}>
                <div className="pa-distribution-total">
                  <span>{t("subscriptions")}</span>
                  <strong>
                    {data.distribution.reduce((sum, row) => sum + row.count, 0)}
                  </strong>
                </div>
                <div className="pa-distribution-bar">
                  {data.distribution.map((row) => (
                    <span key={row.planId} style={{ flex: row.count }} />
                  ))}
                </div>
                <div className="pa-distribution-list">
                  {data.distribution.map((row) => (
                    <Link to={"/admin/billing"} key={row.planId}>
                      <span className="pa-badge">
                        {planLabel(row.planName, row.planId)}
                      </span>
                      <b>{row.count}</b>
                      <span>
                        {Math.round(
                          (row.count /
                            Math.max(
                              1,
                              data.distribution.reduce((s, r) => s + r.count, 0)
                            )) *
                            100
                        )}
                        %
                      </span>
                    </Link>
                  ))}
                </div>
              </Panel>
            </div>
            <div className="pa-overview-bottom">
              <Panel
                title={t("recentCompanies")}
                actions={
                  <Link to="/admin/companies">
                    {t("allCompanies")} <ArrowUpRight size={14} />
                  </Link>
                }
              >
                <div className="pa-record-list">
                  {data.recentCompanies.map((company) => (
                    <div key={company.id}>
                      <Identity
                        name={company.name}
                        to={`/admin/companies/${company.id}`}
                      />
                      <span className="pa-badge">
                        {planLabel(company.planName, company.planId)}
                      </span>
                      {dateLabel(company.createdAt)}
                    </div>
                  ))}
                </div>
              </Panel>
              <Panel
                title={t("recentActivity")}
                actions={<Link to="/admin/audit-logs">{t("allActivity")}</Link>}
              >
                {data.activity.length ? (
                  <div className="pa-activity">
                    {data.activity.map((event) => (
                      <div key={event.id}>
                        <span className="pa-activity-dot" />
                        <div>
                          <strong>{actionLabel(event.action)}</strong>
                          <small>
                            {event.actor} · {dateLabel(event.createdAt, true)}
                          </small>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="pa-empty">
                    <Search size={28} aria-hidden="true" />
                    <p>{t("noActivity")}</p>
                  </div>
                )}
              </Panel>
            </div>
          </>
        )
      )}
    </>
  );
}
