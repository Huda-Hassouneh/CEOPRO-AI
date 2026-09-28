import { useRef } from "react";
import { Link } from "react-router-dom";
import { ArrowUpRight } from "lucide-react";
import { useI18n } from "../../../app/providers/I18nProvider.jsx";
import { useAdminQuery, useAdminText } from "../components/AdminContext.jsx";
import { Heading, Badge, DateValue, Identity } from "../components/AdminUI.jsx";
import { AdminTable, useTableParams } from "../components/AdminTable.jsx";

// These are the statuses produced by mapStripeSubscriptionStatus on the backend.
// Labels come from billing.management.status in the shared en/ar translations.
const SUBSCRIPTION_STATUSES = [
  "active",
  "trialing",
  "past_due",
  "pending",
  "payment_failed",
  "paused",
  "cancelled",
  "expired"
];
const PAGE_SIZES = [8, 20, 50];

export function DirectoryPage({ domain }) {
  const { t } = useAdminText();
  const { t: translate } = useI18n();
  const table = useTableParams();
  const requestedPageSize = Number(table.params.pageSize);
  const pageSize = PAGE_SIZES.includes(requestedPageSize)
    ? requestedPageSize
    : 8;
  // Changing Rows per page updates the URL in AdminTable. The new value is
  // included in the query key and sent to GET /platform-admin/{domain}.
  const query = useAdminQuery(domain, { ...table.params, pageSize });
  const previousFacets = useRef({ domain, value: {} });
  if (previousFacets.current.domain !== domain) {
    previousFacets.current = { domain, value: {} };
  }
  if (query.data?.facets) {
    previousFacets.current.value = query.data.facets;
  }
  // Preserve the filter choices while a different page or filter is loading.
  const facets = query.data?.facets || previousFacets.current.value;
  const plans = facets.plans || [];
  const selectedPlanId = table.params.planId;
  const selectedPlan =
    selectedPlanId && !plans.some((plan) => plan.value === selectedPlanId)
      ? [
          {
            value: selectedPlanId,
            label:
              query.data?.items?.find((row) => row.planId === selectedPlanId)
                ?.planName || t("unknown")
          }
        ]
      : [];
  const created = {
    key: "createdAt",
    render: (row) => <DateValue value={row.createdAt} />
  };
  const status = {
    key: "status",
    label: "statusLabel",
    render: (row) => <Badge value={row.status} />
  };
  const config =
    domain === "companies"
      ? {
          columns: [
            {
              key: "name",
              label: "company",
              render: (row) => (
                <Identity name={row.name} to={`/admin/companies/${row.id}`} />
              )
            },
            {
              key: "industry",
              render: (row) => row.industry || t("unknown")
            },
            { key: "country", render: (row) => row.country || t("unknown") },
            {
              key: "planId",
              render: (row) => row.planName || t("unconfigured"),
              sortable: false
            },
            {
              key: "subscriptionStatus",
              render: (row) =>
                row.subscriptionStatus ? (
                  <span
                    className={`pa-badge pa-badge--${row.subscriptionStatus}`}
                  >
                    {SUBSCRIPTION_STATUSES.includes(row.subscriptionStatus)
                      ? translate(
                          `billing.management.status.${row.subscriptionStatus}`
                        )
                      : t("unknown")}
                  </span>
                ) : (
                  t("unconfigured")
                ),
              sortable: false
            },
            ...["users", "products", "competitors"].map((key) => ({
              key,
              sortable: false
            })),
            created,
            status
          ],
          filters: [
            { key: "planId", options: [...selectedPlan, ...plans] },
            {
              key: "subscriptionStatus",
              options: SUBSCRIPTION_STATUSES.map((value) => ({
                value,
                label: translate(`billing.management.status.${value}`)
              }))
            },
            { key: "status", options: ["active", "suspended"] },
            { key: "country", options: facets.countries || [] }
          ]
        }
      : {
          columns: [
            {
              key: "name",
              render: (row) => (
                <Identity
                  name={row.name}
                  email={row.email}
                  to={`/admin/users/${row.id}`}
                />
              )
            },
            {
              key: "company",
              render: (row) => (
                <Link to={`/admin/companies/${row.companyId}`}>
                  {row.company}
                </Link>
              )
            },
            {
              key: "role",
              label: "companyRole",
              render: (row) => <Badge value={row.role} />
            },
            { ...status, label: "status" },
            { ...created, label: "joined" }
          ],
          filters: [
            {
              key: "companyId",
              label: "company",
              options: facets.companies || []
            },
            {
              key: "role",
              options: ["owner", "admin", "manager", "accountant", "staff"]
            },
            { key: "status", options: ["active", "suspended"] }
          ]
        };
  return (
    <>
      <Heading title={domain} description={`${domain}Description`} />
      <AdminTable
        title={t(domain)}
        query={query}
        table={table}
        {...config}
        rowAction={(row) => (
          <Link
            className="pa-row-action"
            aria-label={`${t("view")}: ${row.name}`}
            to={`/admin/${domain}/${row.id}`}
          >
            <ArrowUpRight size={17} />
          </Link>
        )}
      />
    </>
  );
}
