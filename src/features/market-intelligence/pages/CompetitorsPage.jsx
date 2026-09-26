import { useMemo, useState } from "react";
import { Filter, Plus, Search } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useI18n } from "../../../app/providers/I18nProvider.jsx";
import { DashboardLayout } from "../../../app/layouts/DashboardLayout.jsx";
import PageHeader from "../../../shared/components/layout/PageHeader.jsx";
import Button from "../../../shared/components/ui/Button.jsx";
import Input from "../../../shared/components/ui/Input.jsx";
import Skeleton from "../../../shared/components/ui/Skeleton.jsx";
import EmptyState from "../../../shared/components/ui/EmptyState.jsx";
import { routePaths } from "../../../app/router/routePaths.js";
import { MarketTabs } from "../components/MarketTabs.jsx";
import { CompetitorTable } from "../components/CompetitorTable.jsx";
import { useCompetitors } from "../hooks/useCompetitors.js";
import "../styles/MarketIntelligence.css";

export function CompetitorsPage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const { data: rows = [], isLoading, isError, refetch } = useCompetitors();

  const [query, setQuery] = useState("");
  const [industry, setIndustry] = useState("all");
  const [sort, setSort] = useState("updated");
  const [page, setPage] = useState(1);

  const filteredRows = useMemo(() => {
    if (!rows.length) return [];

    const next = rows.filter(
      (row) =>
        (!query ||
          `${row.name} ${row.website}`
            .toLowerCase()
            .includes(query.toLowerCase())) &&
        (industry === "all" || row.industry === industry)
    );

    return sort === "name"
      ? [...next].sort((a, b) => a.name.localeCompare(b.name))
      : [...next].sort((a, b) => new Date(b.addedAt) - new Date(a.addedAt));
  }, [rows, query, industry, sort]);

  const visibleRows = filteredRows.slice((page - 1) * 10, page * 10);

  return (
    <DashboardLayout>
      <div className="market-page competitors-page">
        <PageHeader
          title={t("market.competitorsPage.title")}
          subtitle={t("market.competitorsPage.subtitle")}
          actions={
            <Button
              size="sm"
              leadingIcon={<Plus size={15} />}
              onClick={() => navigate(routePaths.marketAddCompetitor)}
            >
              {t("market.controls.addCompetitor")}
            </Button>
          }
        />
        <MarketTabs />
        <div className="competitor-filters">
          <Input
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setPage(1);
            }}
            placeholder={t("market.competitorsPage.search")}
            leftIcon={<Search size={17} />}
            aria-label={t("market.competitorsPage.search")}
          />
          <select
            value={industry}
            onChange={(event) => setIndustry(event.target.value)}
            aria-label={t("market.competitorsPage.industry")}
          >
            <option value="all">
              {t("market.competitorsPage.allIndustries")}
            </option>
            {/* You can make these dynamic later by mapping a Set of row.industry */}
            <option value="Telecom">Telecom</option>
            <option value="Internet">Internet</option>
            <option value="Analytics">Analytics</option>
          </select>
          <select
            value={sort}
            onChange={(event) => setSort(event.target.value)}
            aria-label={t("market.competitorsPage.sort")}
          >
            <option value="updated">
              {t("market.competitorsPage.lastUpdated")}
            </option>
            <option value="name">{t("market.competitorsPage.name")}</option>
          </select>
          <Button variant="outline" leadingIcon={<Filter size={16} />}>
            {t("market.competitorsPage.filter")}
          </Button>
        </div>

        <section className="market-panel competitor-list-panel">
          {isLoading ? (
            <div className="market-main-loading" style={{ padding: "2rem" }}>
              <Skeleton height="300px" variant="rectangular" />
            </div>
          ) : isError ? (
            <EmptyState
              title="Error Loading Competitors"
              action={<Button onClick={() => refetch()}>Retry</Button>}
            />
          ) : (
            <>
              <CompetitorTable
                t={t}
                rows={visibleRows}
                onDetails={(id) =>
                  navigate(`${routePaths.marketCompetitors}/${id}`)
                }
              />
              <div className="competitor-pagination">
                <span>
                  {t("market.competitorsPage.showing", {
                    start: filteredRows.length ? (page - 1) * 10 + 1 : 0,
                    end: Math.min(page * 10, filteredRows.length),
                    total: filteredRows.length
                  })}
                </span>
                <div>
                  <button
                    type="button"
                    disabled={page === 1}
                    onClick={() => setPage((value) => value - 1)}
                    aria-label={t("market.competitorsPage.previous")}
                  >
                    ‹
                  </button>
                  <button
                    type="button"
                    className="is-current"
                    aria-current="page"
                  >
                    {page}
                  </button>
                  <button
                    type="button"
                    disabled={page * 10 >= filteredRows.length}
                    onClick={() => setPage((value) => value + 1)}
                    aria-label={t("market.competitorsPage.next")}
                  >
                    ›
                  </button>
                </div>
              </div>
            </>
          )}
        </section>
      </div>
    </DashboardLayout>
  );
}
