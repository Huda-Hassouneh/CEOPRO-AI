import { useQuery } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { useI18n } from "../../../app/providers/I18nProvider.jsx";
import { getApiErrorMessage } from "../../../shared/lib/apiErrors.js";
import Button from "../../../shared/components/ui/Button.jsx";
import Card from "../../../shared/components/ui/Card.jsx";
import Skeleton from "../../../shared/components/ui/Skeleton.jsx";
import { mpiApi } from "../api/mpiApi.js";
import { MarketPerceptionResult } from "./MarketPerceptionResult.jsx";

function PerceptionCard({ tenantId, subjectType, subjectId, title, subtitle }) {
  const { t } = useI18n();
  const query = useQuery({
    queryKey: ["market-perception", tenantId, subjectType, subjectId ?? null],
    queryFn: ({ signal }) => mpiApi.getSummary({ subjectType, subjectId, signal }),
    enabled: false, retry: false
  });
  return <Card className="market-perception-card">
    <div className="market-main-panel__header">
      <div><h3>{title}</h3>{subtitle && <p>{subtitle}</p>}</div>
      <Button size="sm" variant="outline" leadingIcon={<RefreshCw size={14} />}
        disabled={query.isFetching} aria-busy={query.isFetching || undefined}
        onClick={() => query.refetch()}>
        {t(query.data ? "marketPerception.refresh" : "marketPerception.analyze")}
      </Button>
    </div>
    {query.isFetching ? <div aria-busy="true"><Skeleton height="76px" /><p>{t("marketPerception.analyzing")}</p></div> : query.isError ?
      <p role="alert">{getApiErrorMessage(query.error, t)}</p> :
      <MarketPerceptionResult summary={query.data} />}
  </Card>;
}

export function MarketPerceptionPanel({ tenantId, selectedProduct, localize }) {
  const { t } = useI18n();
  return <section className="market-perception-panel" aria-label={t("marketPerception.title")}>
    <div className="market-main-panel__header"><div><h2>{t("marketPerception.title")}</h2><p>{t("marketPerception.subtitle")}</p></div></div>
    <div className={`market-perception-grid ${!selectedProduct ? "is-business-only" : ""}`}>
      <PerceptionCard tenantId={tenantId} subjectType="BUSINESS" title={t("marketPerception.business")} />
      {selectedProduct && <PerceptionCard tenantId={tenantId} subjectType="PRODUCT" subjectId={selectedProduct.id}
        title={t("marketPerception.product")} subtitle={localize(selectedProduct.name)} />}
    </div>
  </section>;
}
