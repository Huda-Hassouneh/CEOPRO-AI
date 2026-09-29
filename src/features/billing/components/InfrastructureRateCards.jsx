import { useEffect, useState } from "react";
import useSWR from "swr";
import { Plus } from "lucide-react";

import Badge from "../../../shared/components/ui/Badge.jsx";
import Button from "../../../shared/components/ui/Button.jsx";
import Input from "../../../shared/components/ui/Input.jsx";
import Modal from "../../../shared/components/ui/Modal.jsx";
import Select from "../../../shared/components/ui/Select.jsx";
import Skeleton from "../../../shared/components/ui/Skeleton.jsx";
import Table from "../../../shared/components/ui/Table.jsx";
import { getApiError } from "../api/billingApi.js";

const swrOptions = { shouldRetryOnError: false, revalidateOnFocus: false };
const tr = (t, key, fallback) => { const value = t(key); return value === key ? fallback : value; };
const blank = (rate = null) => ({
  featureId: rate?.featureId ?? "", costDriver: rate?.costDriver ?? "",
  usageBasis: rate?.usageBasis ?? "limit_value", billingUnit: rate?.billingUnit ?? "",
  billingUnitsPerFeatureUnit: rate?.billingUnitsPerFeatureUnit ?? 1,
  unitCost: rate?.unitCost ?? "", currency: rate?.currency ?? "USD",
  operationalMultiplier: rate?.operationalMultiplier ?? 1,
  variabilityReserve: rate?.variabilityReserve ?? 1,
  verificationStatus: rate?.verificationStatus ?? "unconfirmed", source: rate?.source ?? "",
  effectiveFrom: rate?.effectiveFrom ? String(rate.effectiveFrom).slice(0, 16) : "",
  effectiveTo: rate?.effectiveTo ? String(rate.effectiveTo).slice(0, 16) : "",
});
const number = (value) => Number(value);

function RateModal({ rate, open, onClose, features, api, onSaved, t }) {
  const [form, setForm] = useState(blank(rate));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { if (open) setForm(blank(rate)); }, [open, rate]);
  const set = (key) => (event) => setForm((previous) => ({ ...previous, [key]: event.target.value }));
  const submit = async (event) => {
    event.preventDefault(); setSaving(true); setError("");
    try {
      const payload = {
        featureId: form.featureId || null, costDriver: form.costDriver.trim(), usageBasis: form.usageBasis,
        billingUnit: form.billingUnit.trim(), billingUnitsPerFeatureUnit: number(form.billingUnitsPerFeatureUnit),
        unitCost: number(form.unitCost), currency: form.currency.trim().toUpperCase(),
        operationalMultiplier: number(form.operationalMultiplier), variabilityReserve: number(form.variabilityReserve),
        verificationStatus: form.verificationStatus, source: form.source.trim() || undefined,
        effectiveFrom: form.effectiveFrom ? new Date(form.effectiveFrom).toISOString() : undefined,
        effectiveTo: form.effectiveTo ? new Date(form.effectiveTo).toISOString() : null,
      };
      if (rate) await api.updateInfrastructureRate(rate.id, payload); else await api.createInfrastructureRate(payload);
      await onSaved(); onClose();
    } catch (requestError) { setError(getApiError(requestError).message); } finally { setSaving(false); }
  };
  return <Modal isOpen={open} onClose={saving ? undefined : onClose}
    title={tr(t, rate ? "billing.catalog.customPlans.infrastructureRates.edit" : "billing.catalog.customPlans.infrastructureRates.create", rate ? "Edit infrastructure rate" : "Add infrastructure rate")}
    maxWidth="760px" footer={<><Button variant="outline" onClick={onClose} disabled={saving}>{tr(t, "common.cancel", "Cancel")}</Button><Button type="submit" form="infrastructure-rate-form" loading={saving}>{tr(t, "common.save", "Save")}</Button></>}>
    <form id="infrastructure-rate-form" className="billing-catalog-form" onSubmit={submit}><div className="billing-catalog-form-grid">
      <Select label={tr(t, "billing.catalog.fields.feature", "Feature")} value={form.featureId} onChange={set("featureId")} options={[{ value: "", label: tr(t, "billing.catalog.customPlans.infrastructureRates.unassigned", "Not tied to a feature") }, ...features.map((feature) => ({ value: feature.id, label: feature.name }))]} />
      <Input label={tr(t, "billing.catalog.customPlans.infrastructureRates.costDriver", "Cost driver")} value={form.costDriver} onChange={set("costDriver")} required />
      <Select label={tr(t, "billing.catalog.customPlans.infrastructureRates.usageBasis", "Usage basis")} value={form.usageBasis} onChange={set("usageBasis")} options={["limit_value", "estimated_usage", "enabled_feature"].map((value) => ({ value, label: tr(t, `billing.catalog.customPlans.infrastructureRates.usageBasisValues.${value}`, value) }))} />
      <Input label={tr(t, "billing.catalog.customPlans.infrastructureRates.billingUnit", "Billing unit")} value={form.billingUnit} onChange={set("billingUnit")} required />
      <Input label={tr(t, "billing.catalog.customPlans.infrastructureRates.conversion", "Billing units per feature unit")} hint={tr(t, "billing.catalog.customPlans.infrastructureRates.conversionHint", "For MB to GB-month, configure 0.0009765625.")} type="number" min="0.0000000001" step="0.0000000001" value={form.billingUnitsPerFeatureUnit} onChange={set("billingUnitsPerFeatureUnit")} required />
      <Input label={tr(t, "billing.catalog.customPlans.infrastructureRates.unitCost", "Unit cost")} type="number" min="0" step="0.000001" value={form.unitCost} onChange={set("unitCost")} required />
      <Input label={tr(t, "billing.catalog.fields.currency", "Currency")} maxLength={3} value={form.currency} onChange={set("currency")} required />
      <Input label={tr(t, "billing.catalog.customPlans.infrastructureRates.multiplier", "Operational multiplier")} type="number" min="0.0001" step="0.01" value={form.operationalMultiplier} onChange={set("operationalMultiplier")} required />
      <Input label={tr(t, "billing.catalog.customPlans.infrastructureRates.reserve", "Variability reserve")} type="number" min="1" step="0.01" value={form.variabilityReserve} onChange={set("variabilityReserve")} required />
      <Select label={tr(t, "billing.catalog.fields.status", "Status")} value={form.verificationStatus} onChange={set("verificationStatus")} options={["confirmed", "estimated", "unconfirmed", "deprecated"].map((value) => ({ value, label: tr(t, `billing.catalog.customPlans.infrastructureRates.status.${value}`, value) }))} />
      <Input label={tr(t, "billing.catalog.customPlans.infrastructureRates.effectiveFrom", "Effective from")} type="datetime-local" value={form.effectiveFrom} onChange={set("effectiveFrom")} />
      <Input label={tr(t, "billing.catalog.customPlans.infrastructureRates.effectiveTo", "Effective to")} type="datetime-local" value={form.effectiveTo} onChange={set("effectiveTo")} />
      <Input label={tr(t, "billing.catalog.customPlans.infrastructureRates.source", "Source / evidence")} value={form.source} onChange={set("source")} />
    </div>{error && <p className="billing-inline-error">{error}</p>}</form>
  </Modal>;
}

export default function InfrastructureRateCards({ features, t, locale, api, canManagePricing }) {
  const [createOpen, setCreateOpen] = useState(false); const [editing, setEditing] = useState(null);
  const { data, error, isLoading, mutate } = useSWR("platform-infrastructure-rates", api.getInfrastructureRates, swrOptions);
  const rates = data?.data ?? [];
  const columns = [
    { header: tr(t, "billing.catalog.fields.feature", "Feature"), render: (rate) => rate.feature?.name ?? "-" },
    { header: tr(t, "billing.catalog.customPlans.infrastructureRates.costDriver", "Cost driver"), accessor: "costDriver" },
    { header: tr(t, "billing.catalog.customPlans.infrastructureRates.usageBasis", "Usage basis"), render: (rate) => tr(t, `billing.catalog.customPlans.infrastructureRates.usageBasisValues.${rate.usageBasis}`, rate.usageBasis) },
    { header: tr(t, "billing.catalog.customPlans.infrastructureRates.unitCost", "Unit cost"), render: (rate) => new Intl.NumberFormat(locale, { style: "currency", currency: rate.currency }).format(rate.unitCost) },
    { header: tr(t, "billing.catalog.customPlans.infrastructureRates.billingUnit", "Billing unit"), accessor: "billingUnit" },
    { header: tr(t, "billing.catalog.fields.status", "Status"), render: (rate) => <Badge variant={rate.verificationStatus === "confirmed" ? "success" : rate.verificationStatus === "deprecated" ? "error" : "warning"}>{tr(t, `billing.catalog.customPlans.infrastructureRates.status.${rate.verificationStatus}`, rate.verificationStatus)}</Badge> },
    ...(canManagePricing ? [{ header: tr(t, "billing.catalog.actions", "Actions"), render: (rate) => <Button size="sm" variant="outline" onClick={() => setEditing(rate)}>{tr(t, "common.edit", "Edit")}</Button> }] : []),
  ];
  return <section className="billing-catalog-section billing-custom-plan-rate-section"><div className="billing-catalog-section-heading"><div><h2>{tr(t, "billing.catalog.customPlans.infrastructureRates.title", "Infrastructure Rate Cards")}</h2><p>{tr(t, "billing.catalog.customPlans.infrastructureRates.subtitle", "Internal platform cost drivers used only by authoritative backend pricing.")}</p></div>{canManagePricing && <Button variant="outline" size="sm" leadingIcon={<Plus size={14} />} onClick={() => setCreateOpen(true)}>{tr(t, "billing.catalog.customPlans.infrastructureRates.create", "Add infrastructure rate")}</Button>}</div>{isLoading ? <Skeleton height="180px" variant="rectangular" /> : error ? <p className="billing-inline-error">{getApiError(error).message}</p> : <Table data={rates} columns={columns} ariaLabel={tr(t, "billing.catalog.customPlans.infrastructureRates.title", "Infrastructure Rate Cards")} /> }<RateModal open={createOpen || Boolean(editing)} rate={editing} onClose={() => { setCreateOpen(false); setEditing(null); }} features={features} api={api} onSaved={mutate} t={t} /></section>;
}
