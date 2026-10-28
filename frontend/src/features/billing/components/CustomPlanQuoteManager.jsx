import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ExternalLink, Plus, RefreshCw } from "lucide-react";
import { Link } from "react-router-dom";
import useSWR from "../../../shared/lib/useSWRCompat.js";

import Badge from "./OriginalBillingBadge.jsx";
import BillingOptionsEditor from "./BillingOptionsEditor.jsx";
import Button from "../../../shared/components/ui/Button.jsx";
import Card from "../../../shared/components/ui/Card.jsx";
import Checkbox from "../../../shared/components/ui/Checkbox.jsx";
import EmptyState from "../../../shared/components/ui/EmptyState.jsx";
import Input from "../../../shared/components/ui/Input.jsx";
import Modal from "../../../shared/components/ui/Modal.jsx";
import Select from "../../../shared/components/ui/Select.jsx";
import Skeleton from "../../../shared/components/ui/Skeleton.jsx";
import Stepper from "../../../shared/components/ui/Stepper.jsx";
import Table from "../../../shared/components/ui/Table.jsx";
import Toast from "../../../shared/components/ui/Toast.jsx";
import InfrastructureRateCards from "./InfrastructureRateCards.jsx";
import { routePaths } from "../../../app/router/routePaths.js";
import { billingApi } from "../api/billingApi.js";
import { getApiError, isForbiddenBillingError } from "../api/catalogPresentationErrors.js";

const swrOptions = { shouldRetryOnError: false, revalidateOnFocus: false };
const DEFAULT_FORM = {
  name: "",
  name_ar: "",
  description: "",
  description_ar: "",
  currency: "JOD",
  billingIntervalValue: 1,
  billingIntervalUnit: "month",
  trialPeriodValue: 0,
  billingOptions: [{ period: "monthly", months: 1, intervalUnit: "month", intervalCount: 1, discountPercent: 0 }],
  monthlyInfrastructureCost: 0,
  activePayingTenants: 1,
  estimatedOtherCost: 0,
  targetGrossMarginPercent: 20,
  maxVendorCostRevenueRatioPercent: 20,
  fxRate: "",
  fxSourceCurrency: "USD",
  fxTargetCurrency: "JOD",
  fxSource: "",
  tenantId: "",
  features: {},
};

const formFromQuote = (quote) => {
  if (!quote) return { ...DEFAULT_FORM, features: {} };
  const pricingInputs = quote.pricingInputs ?? {};
  const featureState = Object.fromEntries(
    (quote.quoteFeatures ?? []).map((item) => [
      item.featureId,
      {
        enabled: true,
        limitValue: item.limitValue ?? "",
        estimatedUsage: item.estimatedUsage ?? 0,
        configuration: item.configuration ?? item.metadata?.configuration ?? null,
      },
    ]),
  );

  return {
    ...DEFAULT_FORM,
    name: quote.name ?? "",
    name_ar: quote.nameAr ?? quote.name_ar ?? "",
    description: quote.description ?? "",
    description_ar: quote.descriptionAr ?? quote.description_ar ?? "",
    currency: quote.currency ?? "JOD",
    billingIntervalValue: quote.billingIntervalValue ?? 1,
    billingIntervalUnit: quote.billingIntervalUnit ?? "month",
    trialPeriodValue: quote.trialPeriodValue ?? 0,
    billingOptions:
      Array.isArray(quote.billingOptions) && quote.billingOptions.length
        ? quote.billingOptions.map(
            ({ period, months, discountPercent = 0 }) => ({
              period,
              months,
              intervalUnit: "month",
              intervalCount: months,
              discountPercent,
            }),
          )
        : DEFAULT_FORM.billingOptions,
    monthlyInfrastructureCost: pricingInputs.monthlyInfrastructureCost ?? 0,
    activePayingTenants: pricingInputs.activePayingTenants ?? 1,
    estimatedOtherCost: pricingInputs.estimatedOtherCost ?? 0,
    targetGrossMarginPercent: Number(quote.targetGrossMargin ?? 0.2) * 100,
    maxVendorCostRevenueRatioPercent:
      Number(quote.maxVendorCostRevenueRatio ?? 0.2) * 100,
    fxRate: quote.fxRate ?? "",
    fxSourceCurrency: quote.fxSourceCurrency ?? "USD",
    fxTargetCurrency: quote.fxTargetCurrency ?? quote.currency ?? "JOD",
    fxSource: quote.fxSource ?? "",
    tenantId: quote.tenantId ?? "",
    features: featureState,
  };
};

const tr = (t, key, fallback, params) => {
  const value = t(key, params);
  return value === key ? fallback : value;
};

const numeric = (value, fallback = 0) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
};

const statusVariant = (status) => {
  if (status === "accepted") return "success";
  if (status === "approved" || status === "sent") return "primary";
  if (status === "rejected" || status === "expired") return "error";
  if (status === "calculated") return "warning";
  return "neutral";
};

function money(value, currency, locale) {
  if (value == null || value === "") return "—";
  try {
    return new Intl.NumberFormat(locale, {
      style: "currency",
      currency,
    }).format(Number(value));
  } catch {
    return `${Number(value).toFixed(2)} ${currency}`;
  }
}

function QuoteFormModal({
  open,
  onClose,
  quote,
  features,
  onSaved,
  t,
  locale,
  api = billingApi,
  platformMode = false,
  tenants = [],
  monitoringCadences = [],
}) {
  const { data: effectivePolicy } = useSWR(open && platformMode ? 'custom-plan-pricing-policy' : null, api.getCustomPlanPricingPolicy, swrOptions);
  const intent = useRef(null);
  useEffect(()=>{ if(open) intent.current = globalThis.crypto.randomUUID(); },[open,quote]);
  const editing = Boolean(quote);
  const [step, setStep] = useState(1);
  const [form, setForm] = useState(() => formFromQuote(quote));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) return;
    const initial = formFromQuote(quote);
    if (platformMode) {
      initial.currency = quote?.currency || "USD";
      initial.trialPeriodValue = 0;
      initial.billingOptions = [{ period: "monthly", months: 1, intervalUnit: "month", intervalCount: 1, discountPercent: 0 }];
    }
    setForm(initial);
    setStep(1);
    setError("");
  }, [open, quote, platformMode]);

  useEffect(() => {
    if (!open || !platformMode) return;
    const active = effectivePolicy?.data?.policies?.find(p=>p.status==='active');
    setForm(previous=>({...previous,
      monthlyInfrastructureCost:active?.monthly_shared_infrastructure_cost_usd ?? '',
      activePayingTenants:active?.active_paying_tenant_count ?? '', estimatedOtherCost:'',
      targetGrossMarginPercent:active?.target_gross_margin == null ? '' : Number(active.target_gross_margin)*100,
      maxVendorCostRevenueRatioPercent:active?.max_vendor_cost_revenue_ratio == null ? '' : Number(active.max_vendor_cost_revenue_ratio)*100,
      fxRate:'',fxSourceCurrency:'USD',fxTargetCurrency:'USD',fxSource:'',
    }));
  }, [open,platformMode,effectivePolicy]);

  const reset = () => {
    setStep(1);
    setForm(formFromQuote(null));
    setError("");
  };

  const close = () => {
    if (saving) return;
    reset();
    onClose();
  };

  const setFeature = (feature, enabled) => {
    setForm((current) => ({
      ...current,
      features: {
        ...current.features,
        [feature.id]: enabled
          ? {
              enabled: true,
              limitValue: feature.type === "boolean" ? null : "",
              estimatedUsage: 0,
              ...(feature.code === "competitor_management"
                ? {
                    configuration: {
                      monitoringFrequencyMinutes:
                        monitoringCadences[0]?.minutes ?? "",
                    },
                  }
                : {}),
            }
          : {
              enabled: false,
              limitValue: null,
              estimatedUsage: 0,
              configuration: null,
            },
      },
    }));
  };

  const updateFeature = (featureId, patch) => {
    setForm((current) => ({
      ...current,
      features: {
        ...current.features,
        [featureId]: { ...(current.features[featureId] ?? {}), ...patch },
      },
    }));
  };

  const selected = features.filter(
    (feature) => form.features[feature.id]?.enabled,
  );
  const steps = [
    {
      id: "details",
      label: tr(t, "billing.catalog.customPlans.steps.details", "Plan"),
    },
    {
      id: "features",
      label: tr(t, "billing.catalog.customPlans.steps.features", "Features"),
    },
    {
      id: "costs",
      label: tr(
        t,
        "billing.catalog.customPlans.steps.costs",
        "Cost assumptions",
      ),
    },
    {
      id: "review",
      label: tr(t, "billing.catalog.customPlans.steps.review", "Review"),
    },
  ];

  const validateStep = () => {
    if (step === 1 && platformMode && !editing && !form.tenantId) {
      return tr(
        t,
        "billing.catalog.customPlans.validation.tenant",
        "Select the customer tenant for this quote.",
      );
    }
    if (step === 1 && !platformMode && (!form.name.trim() || !form.name_ar.trim())) {
      return tr(
        t,
        "billing.catalog.customPlans.validation.names",
        "English and Arabic plan names are required.",
      );
    }
    if (step === 1) {
      const invalidOption = !platformMode && (
        !form.billingOptions.length ||
        form.billingOptions.some(
          (option) =>
            !String(option.period || "").trim() ||
            !Number.isInteger(numeric(option.months, 0)) ||
            numeric(option.months, 0) <= 0 ||
            numeric(option.discountPercent, -1) < 0 ||
            numeric(option.discountPercent, 101) > 100,
        ));
      if (invalidOption)
        return tr(
          t,
          "billing.catalog.validation.billingOption",
          "Each billing option needs a period code, positive month count, and 0–100% discount.",
        );
    }
    if (step === 2 && selected.length === 0) {
      return tr(
        t,
        "billing.catalog.customPlans.validation.feature",
        "Select at least one feature.",
      );
    }
    if (step === 2) {
      const invalidLimit = selected.some(
        (feature) =>
          feature.type !== "boolean" &&
          form.features[feature.id]?.limitValue !== "" &&
          numeric(form.features[feature.id]?.limitValue, -1) < 0,
      );
      if (invalidLimit)
        return tr(
          t,
          "billing.catalog.customPlans.validation.limit",
          "Feature limits cannot be negative.",
        );

      const monitoringFeature = selected.find(
        (feature) => feature.code === "competitor_management",
      );
      const competitorCapacity = selected.find(
        (feature) => feature.code === "tracked_competitors",
      );
      if (
        monitoringFeature &&
        (!Number.isInteger(
          numeric(
            form.features[monitoringFeature.id]?.configuration
              ?.monitoringFrequencyMinutes,
            0,
          ),
        ) ||
          numeric(
            form.features[monitoringFeature.id]?.configuration
              ?.monitoringFrequencyMinutes,
            0,
          ) <= 0)
      ) {
        return tr(
          t,
          "billing.catalog.customPlans.validation.monitoringCadence",
          "Select a monitoring cadence for competitor management.",
        );
      }
      if (
        monitoringFeature &&
        (!competitorCapacity ||
          numeric(form.features[competitorCapacity.id]?.limitValue, 0) <= 0)
      ) {
        return tr(
          t,
          "billing.catalog.customPlans.validation.trackedCompetitors",
          "Select tracked competitors with a positive limit when competitor management is enabled.",
        );
      }
    }
    if (step === 3 && !platformMode) {
      const gross = numeric(form.targetGrossMarginPercent, -1);
      const ratio = numeric(form.maxVendorCostRevenueRatioPercent, -1);
      if (gross < 0 || gross >= 100 || ratio <= 0 || ratio > 100) {
        return tr(
          t,
          "billing.catalog.customPlans.validation.policy",
          "Gross margin must be 0–99.99% and vendor cost ratio must be above 0 and at most 100%.",
        );
      }
    }
    return "";
  };

  const next = () => {
    const issue = validateStep();
    if (issue) return setError(issue);
    setError("");
    setStep((current) => Math.min(4, current + 1));
  };

  const submit = async () => {
    const issue = validateStep();
    if (issue) return setError(issue);
    setSaving(true);
    setError("");
    try {
      const payload = {
        idempotencyKey: intent.current,
        ...(platformMode && !editing ? { tenantId: form.tenantId } : {}),
        name: form.name.trim(),
        name_ar: form.name_ar.trim(),
        description: form.description.trim() || undefined,
        description_ar: form.description_ar.trim() || undefined,
        currency: form.currency.trim().toUpperCase(),
        billingIntervalValue: numeric(form.billingIntervalValue, 1),
        billingIntervalUnit: form.billingIntervalUnit,
        trialPeriodValue: numeric(form.trialPeriodValue, 0),
        billingOptions: form.billingOptions.map((option) => ({
          period: String(option.period).trim(),
          months: Math.trunc(numeric(option.months, 1)),
          discountPercent: numeric(option.discountPercent),
        })),
        features: selected.map((feature) => ({
          featureId: feature.id,
          limitValue:
            feature.type === "boolean" ||
            form.features[feature.id]?.limitValue === ""
              ? null
              : numeric(form.features[feature.id]?.limitValue),
          estimatedUsage: numeric(form.features[feature.id]?.estimatedUsage),
          ...(feature.code === "competitor_management"
            ? {
                configuration: {
                  monitoringFrequencyMinutes: numeric(
                    form.features[feature.id]?.configuration
                      ?.monitoringFrequencyMinutes,
                  ),
                },
              }
            : {}),
        })),
        monthlyInfrastructureCost: numeric(form.monthlyInfrastructureCost),
        activePayingTenants: Math.max(
          1,
          Math.trunc(numeric(form.activePayingTenants, 1)),
        ),
        estimatedOtherCost: numeric(form.estimatedOtherCost),
        targetGrossMargin: numeric(form.targetGrossMarginPercent) / 100,
        maxVendorCostRevenueRatio:
          numeric(form.maxVendorCostRevenueRatioPercent) / 100,
        ...(form.fxRate
          ? {
              fxRate: numeric(form.fxRate),
              fxSourceCurrency: form.fxSourceCurrency.trim().toUpperCase(),
              fxTargetCurrency: form.fxTargetCurrency.trim().toUpperCase(),
              fxSource: form.fxSource.trim() || undefined,
              fxRateAt: new Date().toISOString(),
            }
          : {}),
      };
      const response = editing
        ? await api.updateCustomPlanQuote(quote.id, payload)
        : await api.createCustomPlanQuote(payload);
      const savedQuote = response?.data;
      let pricingError = '';
      if (savedQuote?.id) {
        try { await api.calculateCustomPlanQuote(savedQuote.id); }
        catch (e) { pricingError = getApiError(e).message; }
      }
      // The request is durable even if calculation is unavailable. Do not invite duplicate creation.
      await onSaved({savedQuote, pricingError});
      close();
    } catch (requestError) {
      setError(getApiError(requestError).message);
    } finally {
      setSaving(false);
    }
  };

  const footer = (
    <>
      <Button
        variant="outline"
        onClick={step === 1 ? close : () => setStep((current) => current - 1)}
        disabled={saving}
      >
        {step === 1
          ? tr(t, "common.cancel", "Cancel")
          : tr(t, "common.back", "Back")}
      </Button>
      {step < 4 ? (
        <Button onClick={next}>{tr(t, "common.continue", "Continue")}</Button>
      ) : (
        <Button onClick={submit} loading={saving}>
          {editing
            ? tr(
                t,
                "billing.catalog.customPlans.updateQuote",
                "Update & calculate quote",
              )
            : tr(
                t,
                "billing.catalog.customPlans.createQuote",
                "Create & calculate quote",
              )}
        </Button>
      )}
    </>
  );

  return (
    <Modal
      isOpen={open}
      onClose={close}
      title={
        editing
          ? tr(
              t,
              "billing.catalog.customPlans.editTitle",
              "Edit Custom Plan Quote",
            )
          : tr(
              t,
              "billing.catalog.customPlans.createTitle",
              "Create Custom Plan Quote",
            )
      }
      maxWidth="900px"
      footer={footer}
    >
      <Stepper
        steps={steps}
        currentStep={step}
        ariaLabel={tr(
          t,
          "billing.catalog.customPlans.createTitle",
          "Create Custom Plan Quote",
        )}
      />

      {step === 1 && (
        <div className="billing-catalog-form billing-custom-plan-step">
          <div className="billing-catalog-form-grid">
            {platformMode && (
              <Select
                label={tr(t, "billing.catalog.customPlans.tenant", "Customer tenant")}
                value={form.tenantId}
                disabled={editing}
                onChange={(event) => setForm({ ...form, tenantId: event.target.value })}
                options={[
                  {
                    value: "",
                    label: tr(
                      t,
                      "billing.catalog.customPlans.selectTenant",
                      "Select tenant",
                    ),
                  },
                  ...tenants.map((tenant) => ({
                    value: tenant.id,
                    label: tenant.businessName || tenant.id,
                  })),
                ]}
              />
            )}
            <Input
              label={platformMode ? tr(t, "billing.catalog.customPlans.requestLabel", "Internal request label") : tr(t, "billing.catalog.fields.name", "Name")}
              value={form.name}
              maxLength={50}
              onChange={(event) =>
                setForm({ ...form, name: event.target.value })
              }
              required={!platformMode}
            />
            <Input
              label={platformMode ? tr(t, "billing.catalog.customPlans.requestLabelAr", "Internal request label (Arabic)") : tr(t, "billing.catalog.fields.nameAr", "Arabic name")}
              value={form.name_ar}
              maxLength={50}
              dir="rtl"
              onChange={(event) =>
                setForm({ ...form, name_ar: event.target.value })
              }
              required={!platformMode}
            />
            <Input
              label={tr(t, "billing.catalog.fields.currency", "Currency")}
              value={form.currency}
              maxLength={3}
              disabled={platformMode}
              onChange={(event) =>
                setForm({ ...form, currency: event.target.value.toUpperCase() })
              }
            />
            <Input
              label={tr(t, "billing.catalog.fields.trialDays", "Trial days")}
              type="number"
              min="0"
              value={form.trialPeriodValue}
              disabled={platformMode}
              onChange={(event) =>
                setForm({ ...form, trialPeriodValue: event.target.value })
              }
            />
          </div>
          <div className="billing-catalog-textarea-grid">
            <label className="billing-catalog-textarea-field">
              <span className="ceopro-label">
                {tr(t, "billing.catalog.fields.description", "Description")}
              </span>
              <textarea
                rows="3"
                value={form.description}
                onChange={(event) =>
                  setForm({ ...form, description: event.target.value })
                }
              />
            </label>
            <label className="billing-catalog-textarea-field">
              <span className="ceopro-label">
                {tr(
                  t,
                  "billing.catalog.fields.descriptionAr",
                  "Arabic description",
                )}
              </span>
              <textarea
                rows="3"
                dir="rtl"
                value={form.description_ar}
                onChange={(event) =>
                  setForm({ ...form, description_ar: event.target.value })
                }
              />
            </label>
          </div>
          {platformMode && <p className="billing-catalog-permission-note">{tr(t, "billing.catalog.customPlans.pythonMonthlyUsdTerms", "Custom quotes use USD monthly terms; trial and term changes require an approved policy.")}</p>}
          <fieldset disabled={platformMode} style={{border:0,padding:0,margin:0,minWidth:0}}>
            <BillingOptionsEditor options={form.billingOptions} onChange={(billingOptions)=>setForm({...form,billingOptions})} t={t} />
          </fieldset>
        </div>
      )}

      {step === 2 && (
        <div className="billing-custom-plan-feature-list">
          {features.map((feature) => {
            const state = form.features[feature.id] ?? {};
            const label =
              locale === "ar" && feature.name_ar
                ? feature.name_ar
                : feature.name;
            return (
              <Card
                key={feature.id}
                className="billing-custom-plan-feature-row"
              >
                <Checkbox
                  checked={Boolean(state.enabled)}
                  onChange={(event) =>
                    setFeature(feature, event.target.checked)
                  }
                >
                  {label}
                </Checkbox>
                <div className="billing-custom-plan-feature-inputs">
                  {feature.type !== "boolean" && (
                    <Input
                      label={tr(t, "billing.catalog.fields.limit", "Limit")}
                      type="number"
                      min="0"
                      value={state.limitValue ?? ""}
                      disabled={!state.enabled}
                      onChange={(event) =>
                        updateFeature(feature.id, {
                          limitValue: event.target.value,
                        })
                      }
                    />
                  )}
                  <Input
                    label={tr(
                      t,
                      "billing.catalog.customPlans.estimatedUsage",
                      "Estimated monthly usage",
                    )}
                    type="number"
                    min="0"
                    step="0.01"
                    value={platformMode ? (feature.type === "boolean" ? 1 : state.limitValue || 0) : state.estimatedUsage ?? 0}
                    disabled={platformMode || !state.enabled}
                    hint={platformMode ? tr(t,"billing.catalog.legacyRestoration.usageDerived","Python derives pricing usage from the selected allowance and approved cost binding.") : undefined}
                    onChange={(event) =>
                      updateFeature(feature.id, {
                        estimatedUsage: event.target.value,
                      })
                    }
                  />
                  {feature.code === "competitor_management" && (
                    <Select
                      label={tr(
                        t,
                        "billing.custom.monitoringCadence.label",
                        "Monitoring cadence",
                      )}
                      hint={tr(
                        t,
                        "billing.custom.monitoringCadence.adminDescription",
                        "Used with the tracked competitor count to calculate rate-specific vendor usage.",
                      )}
                      value={
                        state.configuration?.monitoringFrequencyMinutes ?? ""
                      }
                      disabled={!state.enabled}
                      onChange={(event) =>
                        updateFeature(feature.id, {
                          configuration: {
                            monitoringFrequencyMinutes: Number(
                              event.target.value,
                            ),
                          },
                        })
                      }
                      options={[
                        {
                          value: "",
                          label: tr(
                            t,
                            "billing.custom.monitoringCadence.select",
                            "Select cadence",
                          ),
                        },
                        ...monitoringCadences.map((cadence) => ({
                          value: cadence.minutes,
                          label: tr(
                            t,
                            `billing.custom.monitoringCadence.options.${cadence.code}`,
                            cadence.code,
                          ),
                        })),
                      ]}
                    />
                  )}
                </div>
              </Card>
            );
          })}
        </div>
      )}

      {step === 3 && (
        <div className="billing-catalog-form billing-custom-plan-step">
          {platformMode && <p className="billing-catalog-permission-note">{tr(t,"billing.catalog.customPlans.pythonPricingAuthority","Values come from the effective versioned Python policy. Quote-local economic overrides are not authorized.")}</p>}
          <fieldset disabled={platformMode} className="billing-catalog-form-grid">
            <Input
              label={tr(
                t,
                "billing.catalog.customPlans.infrastructure",
                "Shared infrastructure cost / month",
              )}
              type="number"
              min="0"
              step="0.01"
              value={form.monthlyInfrastructureCost}
              onChange={(event) =>
                setForm({
                  ...form,
                  monthlyInfrastructureCost: event.target.value,
                })
              }
            />
            <Input
              label={tr(
                t,
                "billing.catalog.customPlans.activeTenants",
                "Active paying tenants",
              )}
              type="number"
              min="1"
              step="1"
              value={form.activePayingTenants}
              onChange={(event) =>
                setForm({ ...form, activePayingTenants: event.target.value })
              }
            />
            <Input
              label={tr(
                t,
                "billing.catalog.customPlans.otherCost",
                "Other included monthly cost",
              )}
              type="number"
              min="0"
              step="0.01"
              value={form.estimatedOtherCost}
              onChange={(event) =>
                setForm({ ...form, estimatedOtherCost: event.target.value })
              }
            />
            <Input
              label={tr(
                t,
                "billing.catalog.customPlans.targetMargin",
                "Target gross margin %",
              )}
              type="number"
              min="0"
              max="99.99"
              step="0.01"
              value={form.targetGrossMarginPercent}
              onChange={(event) =>
                setForm({
                  ...form,
                  targetGrossMarginPercent: event.target.value,
                })
              }
            />
            <Input
              label={tr(
                t,
                "billing.catalog.customPlans.maxVendorRatio",
                "Max vendor-cost / revenue %",
              )}
              type="number"
              min="0.01"
              max="100"
              step="0.01"
              value={form.maxVendorCostRevenueRatioPercent}
              onChange={(event) =>
                setForm({
                  ...form,
                  maxVendorCostRevenueRatioPercent: event.target.value,
                })
              }
            />
          </fieldset>
          <div className="billing-catalog-subsection">
            <div className="billing-catalog-subsection-header">
              <div>
                <h3>
                  {tr(
                    t,
                    "billing.catalog.customPlans.fxTitle",
                    "Optional FX snapshot",
                  )}
                </h3>
                <p>
                  {tr(
                    t,
                    "billing.catalog.customPlans.fxHelp",
                    "Required when an active vendor rate uses a different currency from the quote.",
                  )}
                </p>
              </div>
            </div>
            <fieldset disabled={platformMode} className="billing-catalog-form-grid">
              <Input
                label={tr(t, "billing.catalog.customPlans.fxRate", "FX rate")}
                type="number"
                min="0"
                step="0.000001"
                value={form.fxRate}
                onChange={(event) =>
                  setForm({ ...form, fxRate: event.target.value })
                }
              />
              <Input
                label={tr(
                  t,
                  "billing.catalog.customPlans.fxFrom",
                  "From currency",
                )}
                maxLength={3}
                value={form.fxSourceCurrency}
                onChange={(event) =>
                  setForm({
                    ...form,
                    fxSourceCurrency: event.target.value.toUpperCase(),
                  })
                }
              />
              <Input
                label={tr(t, "billing.catalog.customPlans.fxTo", "To currency")}
                maxLength={3}
                value={form.fxTargetCurrency}
                onChange={(event) =>
                  setForm({
                    ...form,
                    fxTargetCurrency: event.target.value.toUpperCase(),
                  })
                }
              />
              <Input
                label={tr(
                  t,
                  "billing.catalog.customPlans.fxSource",
                  "FX source",
                )}
                value={form.fxSource}
                onChange={(event) =>
                  setForm({ ...form, fxSource: event.target.value })
                }
              />
            </fieldset>
          </div>
        </div>
      )}

      {step === 4 && (
        <div className="billing-custom-plan-review">
          <Card>
            <h3>{form.name}</h3>
            <p>
              {selected.length}{" "}
              {tr(
                t,
                "billing.catalog.customPlans.featuresSelected",
                "features selected",
              )}
            </p>
          </Card>
          <dl className="billing-custom-plan-review-grid">
            <div>
              <dt>
                {tr(
                  t,
                  "billing.catalog.customPlans.targetMargin",
                  "Target gross margin %",
                )}
              </dt>
              <dd>{numeric(form.targetGrossMarginPercent)}%</dd>
            </div>
            <div>
              <dt>
                {tr(
                  t,
                  "billing.catalog.customPlans.maxVendorRatio",
                  "Max vendor-cost / revenue %",
                )}
              </dt>
              <dd>{numeric(form.maxVendorCostRevenueRatioPercent)}%</dd>
            </div>
            <div>
              <dt>
                {tr(
                  t,
                  "billing.catalog.customPlans.infrastructure",
                  "Shared infrastructure cost / month",
                )}
              </dt>
              <dd>
                {money(form.monthlyInfrastructureCost, form.currency, locale)}
              </dd>
            </div>
            <div>
              <dt>
                {tr(
                  t,
                  "billing.catalog.customPlans.activeTenants",
                  "Active paying tenants",
                )}
              </dt>
              <dd>{platformMode && form.activePayingTenants === "" ? "—" : numeric(form.activePayingTenants, 1)}</dd>
            </div>
          </dl>
          <p className="billing-catalog-permission-note">
            {tr(
              t,
              "billing.catalog.customPlans.serverPricingNotice",
              "The backend calculates all authoritative vendor costs and pricing floors after this draft is created.",
            )}
          </p>
        </div>
      )}

      {error && <p className="billing-inline-error">{error}</p>}
    </Modal>
  );
}

export function QuoteReviewModal({quote, onClose, api, t, locale}) {
  const {data,error,isLoading} = useSWR(quote ? ['owner-quote-review',quote.id] : null, ()=>api.getCustomPlanQuote(quote.id), swrOptions);
  const detail = data?.data;
  const sections = detail ? [
    ['configuration',detail.configuration],['quantities',detail.quantities],
    ['pricingEvidence',detail.pricingSnapshot],['revisions',detail.revisions],
    ['auditHistory',detail.events],['checkoutAttempts',detail.checkout_attempts],
  ] : [];
  return <Modal isOpen={Boolean(quote)} onClose={onClose} maxWidth="960px" title={tr(t,'billing.catalog.legacyRestoration.reviewTitle','Quote review and evidence')} footer={<Button variant="outline" onClick={onClose}>{tr(t,'common.close','Close')}</Button>}>
    {isLoading ? <Skeleton height="220px" variant="rectangular"/> : error ? <p role="alert" className="billing-inline-error">{getApiError(error).message}</p> : detail && <div className="billing-catalog-form">
      <Card className="billing-custom-plan-price-summary"><strong>{detail.name}</strong><Badge variant={statusVariant(detail.status)}>{detail.status}</Badge><span>{tr(t,'billing.catalog.customPlans.finalPrice','Final customer price')}: {money(detail.finalPrice,detail.currency,locale)}</span></Card>
      <p>{tr(t,'billing.catalog.legacyRestoration.activationBoundary','Approval and customer acceptance do not grant paid rights. Verified billing confirmation is required.')}</p>
      {sections.map(([key,value])=><details key={key}><summary>{tr(t,'billing.catalog.legacyRestoration.'+key,key)}</summary><pre className="billing-custom-plan-configuration">{JSON.stringify(value ?? null,null,2)}</pre></details>)}
    </div>}
  </Modal>;
}

export function ApproveQuoteModal({ quote, onClose, onApproved, t, locale, api = billingApi, platformMode = false }) {
  const [price, setPrice] = useState(
    quote?.recommendedPrice ?? quote?.minimumSafePrice ?? "",
  );
  const [overrideReason, setOverrideReason] = useState("");
  const [approvalReference, setApprovalReference] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const belowFloor = quote && numeric(price) < numeric(quote.minimumSafePrice);

  useEffect(() => {
    setPrice(quote?.recommendedPrice ?? quote?.minimumSafePrice ?? "");
    setOverrideReason("");
    setApprovalReference("");
    setError("");
  }, [quote]);

  const approve = async () => {
    setSaving(true);
    setError("");
    try {
      if (platformMode && !approvalReference.trim()) throw new Error(tr(t,"billing.catalog.legacyRestoration.evidenceRequired","Approval evidence is required."));
      await api.approveCustomPlanQuote(quote.id, {
        ...(platformMode ? {approvalReference:approvalReference.trim()} : {}),
        finalPrice: numeric(price),
        ...(belowFloor && overrideReason.trim()
          ? { overrideReason: overrideReason.trim() }
          : {}),
      });
      await onApproved();
      onClose();
    } catch (requestError) {
      setError(getApiError(requestError).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      isOpen={Boolean(quote)}
      onClose={saving ? undefined : onClose}
      title={tr(
        t,
        "billing.catalog.customPlans.approveTitle",
        "Approve Custom Plan Price",
      )}
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={saving}>
            {tr(t, "common.cancel", "Cancel")}
          </Button>
          <Button onClick={approve} loading={saving}>
            {tr(t, "billing.catalog.customPlans.approve", "Approve price")}
          </Button>
        </>
      }
    >
      <div className="billing-catalog-form">
        <Card className="billing-custom-plan-price-summary">
          <span>
            {tr(
              t,
              "billing.catalog.customPlans.minimumSafePrice",
              "Minimum safe price",
            )}
          </span>
          <strong>
            {money(quote?.minimumSafePrice, quote?.currency ?? "JOD", locale)}
          </strong>
          {quote?.recommendedPrice != null && (
            <small>
              {tr(
                t,
                "billing.catalog.customPlans.recommendedAutomatedPrice",
                "Recommended automated price",
              )}: {" "}
              {money(quote.recommendedPrice, quote?.currency ?? "JOD", locale)}
            </small>
          )}
        </Card>
        <Input
          label={tr(
            t,
            "billing.catalog.customPlans.finalPrice",
            "Final customer price",
          )}
          type="number"
          min="0.01"
          step="0.01"
          value={price}
          disabled={platformMode}
          onChange={(event) => setPrice(event.target.value)}
        />
        {platformMode && <Input label={tr(t,"billing.catalog.fields.approvalReference","Approval reference")} required value={approvalReference} onChange={e=>setApprovalReference(e.target.value)} />}
        {belowFloor && !platformMode && (
          <label className="billing-catalog-textarea-field">
            <span className="ceopro-label">
              {tr(
                t,
                "billing.catalog.customPlans.overrideReason",
                "Authorized override reason",
              )}
            </span>
            <textarea
              rows="3"
              value={overrideReason}
              onChange={(event) => setOverrideReason(event.target.value)}
            />
          </label>
        )}
        {belowFloor && (
          <p className="billing-inline-error">
            {tr(
              t,
              "billing.catalog.customPlans.belowFloor",
              "This price is below the backend-calculated safe floor. Only an authorized override can approve it.",
            )}
          </p>
        )}
        {error && <p className="billing-inline-error">{error}</p>}
      </div>
    </Modal>
  );
}

const vendorRateForm = (rate = null) => ({
  id: rate?.id ?? "",
  featureId: rate?.featureId ?? "",
  budgetKind: rate?.budgetKind ?? "data",
  policyVersionId: rate?.policyVersionId ?? "",
  usageBasis: rate?.usageBasis ?? "limit_value",
  unitsPerFeatureUnit: rate?.unitsPerFeatureUnit ?? 1,
  verifiedAt: "",
  effectiveFrom: "",
  effectiveTo: "",
  vendor: rate?.vendor ?? "",
  service: rate?.service ?? "",
  billingUnit: rate?.billingUnit ?? "",
  unitCost: rate?.unitCost ?? "",
  currency: rate?.currency ?? "USD",
  operationalMultiplier: rate?.operationalMultiplier ?? 1,
  variabilityReserve: rate?.variabilityReserve ?? 1,
  verificationStatus: rate?.verificationStatus ?? "unconfirmed",
  source: rate?.source ?? "",
  unitsPerCompetitorCheck:
    rate?.metadata?.usageAssumption?.unitsPerCompetitorCheck ?? "",
  metadata: rate?.metadata ?? {},
});

function VendorRateModal({ open, onClose, rate, features, onSaved, t, api = billingApi }) {
  const [form, setForm] = useState(() => vendorRateForm(rate));
  const { data: policyResponse, error: policyError, isLoading: policiesLoading } = useSWR(
    "custom-plan-pricing-policy", api.getCustomPlanPricingPolicy, swrOptions,
  );
  const draftPolicies = policyResponse?.data?.policies?.filter((policy) => policy.status === "draft") ?? [];
  const editing = Boolean(rate?.id);
  useEffect(() => {
    if (open) setForm(vendorRateForm(rate));
  }, [open, rate]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const selectedFeature = features.find(
    (feature) => feature.id === form.featureId,
  );

  const submit = async (event) => {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      if (form.currency.trim().toUpperCase() !== "USD") throw new Error("Python Custom Plan cost schedules currently require USD rates; no currency conversion is applied.");
      if (form.verificationStatus !== "confirmed") throw new Error("Python pricing accepts only verified provider rates. Select Confirmed only when supported by the source evidence.");
      if (!form.verifiedAt || !form.effectiveFrom) throw new Error("Enter the date the rate was verified and its effective start date.");
      if (form.featureId && !form.policyVersionId) throw new Error("Choose a draft pricing policy to bind this feature cost.");
      if (form.featureId && !draftPolicies.some((policy) => policy.policy_version_id === form.policyVersionId)) throw new Error("Choose an available draft policy. Active pricing policies are immutable.");
      const payload = {
        featureId: form.featureId || null,
        budgetKind: form.budgetKind,
        policyVersionId: form.policyVersionId || null,
        usageBasis: form.usageBasis,
        unitsPerFeatureUnit: selectedFeature?.code === "competitor_management" ? numeric(form.unitsPerCompetitorCheck) : numeric(form.unitsPerFeatureUnit, 1),
        verifiedAt: form.verifiedAt,
        effectiveFrom: new Date(form.effectiveFrom).toISOString(),
        effectiveTo: form.effectiveTo ? new Date(form.effectiveTo).toISOString() : null,
        vendor: form.vendor.trim(),
        service: form.service.trim(),
        billingUnit: form.billingUnit.trim(),
        unitCost: numeric(form.unitCost),
        currency: form.currency.trim().toUpperCase(),
        operationalMultiplier: numeric(form.operationalMultiplier, 1),
        variabilityReserve: numeric(form.variabilityReserve, 1),
        verificationStatus: form.verificationStatus,
        source: form.source.trim() || undefined,
        ...(selectedFeature?.code === "competitor_management"
          ? {
              metadata: {
                ...(form.metadata ?? {}),
                usageAssumption: {
                  model: "competitor_monitoring",
                  unitsPerCompetitorCheck: numeric(
                    form.unitsPerCompetitorCheck,
                  ),
                },
              },
            }
          : {}),
      };
      if (editing) await api.updateVendorRate(rate.id, payload);
      else await api.createVendorRate(payload);
      await onSaved();
      onClose();
      setForm(vendorRateForm());
    } catch (requestError) {
      setError(getApiError(requestError).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      isOpen={open}
      onClose={saving ? undefined : onClose}
      title={tr(
        t,
        editing
          ? "billing.catalog.customPlans.vendorRates.edit"
          : "billing.catalog.customPlans.vendorRates.create",
        editing ? "Edit vendor rate" : "Add vendor rate",
      )}
      maxWidth="760px"
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={saving}>
            {tr(t, "common.cancel", "Cancel")}
          </Button>
          <Button type="submit" form="vendor-rate-form" loading={saving}>
            {tr(t, "common.save", "Save")}
          </Button>
        </>
      }
    >
      <form
        id="vendor-rate-form"
        className="billing-catalog-form"
        onSubmit={submit}
      >
        <div className="billing-catalog-form-grid">
          <Select
            label={tr(t, "billing.catalog.fields.feature", "Feature")}
            value={form.featureId}
            onChange={(event) =>
              setForm({ ...form, featureId: event.target.value })
            }
            options={[
              {
                value: "",
                label: tr(
                  t,
                  "billing.catalog.customPlans.vendorRates.unassigned",
                  "Not tied to a feature",
                ),
              },
              ...features.map((feature) => ({
                value: feature.id,
                label: feature.name,
              })),
            ]}
          />
          <Select
            label={tr(t, "billing.catalog.customPlans.vendorRates.budgetKind", "Cost budget")}
            value={form.budgetKind}
            onChange={(event) => setForm({ ...form, budgetKind: event.target.value })}
            options={["data", "ai"].map((value) => ({ value, label: value.toUpperCase() }))}
          />
          {form.featureId && (
            <Select
              label={tr(t, "billing.catalog.customPlans.vendorRates.draftPolicy", "Draft pricing policy")}
              value={form.policyVersionId}
              onChange={(event) => setForm({ ...form, policyVersionId: event.target.value })}
              disabled={policiesLoading || draftPolicies.length === 0}
              options={[{ value: "", label: policiesLoading ? "Loading?" : "Select a draft policy" }, ...draftPolicies.map((policy) => ({ value: policy.policy_version_id, label: `Draft v${policy.version_number}` }))]}
            />
          )}
          {form.featureId && <Select
            label={tr(t, "billing.catalog.customPlans.vendorRates.usageBasisLabel", "Cost usage basis")}
            value={form.usageBasis}
            onChange={(event) => setForm({ ...form, usageBasis: event.target.value })}
            options={["limit_value", "enabled_feature"].map((value) => ({ value, label: tr(t, `billing.catalog.customPlans.vendorRates.usageBasis.${value}`, value) }))}
          />}
          {form.featureId && selectedFeature?.code !== "competitor_management" && <Input
            label={tr(t, "billing.catalog.customPlans.vendorRates.unitsPerFeatureUnit", "Billing units per feature unit")}
            type="number" min="0.00000001" step="0.00000001" value={form.unitsPerFeatureUnit}
            onChange={(event) => setForm({ ...form, unitsPerFeatureUnit: event.target.value })} required
          />}
          <Input
            label={tr(t, "billing.catalog.customPlans.vendorRates.verifiedAt", "Verified on")}
            type="date" value={form.verifiedAt}
            onChange={(event) => setForm({ ...form, verifiedAt: event.target.value })} required
          />
          <Input
            label={tr(t, "billing.catalog.customPlans.vendorRates.effectiveFrom", "Effective from")}
            type="datetime-local" value={form.effectiveFrom}
            onChange={(event) => setForm({ ...form, effectiveFrom: event.target.value })} required
          />
          <Input
            label={tr(t, "billing.catalog.customPlans.vendorRates.effectiveTo", "Effective to")}
            type="datetime-local" value={form.effectiveTo}
            onChange={(event) => setForm({ ...form, effectiveTo: event.target.value })}
          />
          {policyError && <p className="billing-inline-error">{getApiError(policyError).message}</p>}
          {form.featureId && !policiesLoading && draftPolicies.length === 0 && <p className="billing-inline-error">No draft pricing policy is available. Create a draft policy before binding this rate.</p>}
          <Input
            label={tr(
              t,
              "billing.catalog.customPlans.vendorRates.vendor",
              "Vendor",
            )}
            value={form.vendor}
            onChange={(event) =>
              setForm({ ...form, vendor: event.target.value })
            }
            required
          />
          <Input
            label={tr(
              t,
              "billing.catalog.customPlans.vendorRates.service",
              "Service",
            )}
            value={form.service}
            onChange={(event) =>
              setForm({ ...form, service: event.target.value })
            }
            required
          />
          {selectedFeature?.code === "competitor_management" && (
            <Input
              label={tr(
                t,
                "billing.catalog.customPlans.vendorRates.unitsPerCompetitorCheck",
                "Units per competitor check",
              )}
              hint={tr(
                t,
                "billing.catalog.customPlans.vendorRates.unitsPerCompetitorCheckHelp",
                "Rate-specific quantity in the billing unit above (for example CU or credits).",
              )}
              type="number"
              min="0.000001"
              step="0.000001"
              value={form.unitsPerCompetitorCheck}
              onChange={(event) =>
                setForm({
                  ...form,
                  unitsPerCompetitorCheck: event.target.value,
                })
              }
              required
            />
          )}
          <Input
            label={tr(
              t,
              "billing.catalog.customPlans.vendorRates.unit",
              "Billing unit",
            )}
            value={form.billingUnit}
            onChange={(event) =>
              setForm({ ...form, billingUnit: event.target.value })
            }
            required
          />
          <Input
            label={tr(
              t,
              "billing.catalog.customPlans.vendorRates.unitCost",
              "Unit cost",
            )}
            type="number"
            min="0"
            step="0.000001"
            value={form.unitCost}
            onChange={(event) =>
              setForm({ ...form, unitCost: event.target.value })
            }
            required
          />
          <Input
            label={tr(t, "billing.catalog.fields.currency", "Currency")}
            maxLength={3}
            value={form.currency}
            onChange={(event) =>
              setForm({ ...form, currency: event.target.value.toUpperCase() })
            }
            required
          />
          <Input
            label={tr(
              t,
              "billing.catalog.customPlans.vendorRates.operationalMultiplier",
              "Operational multiplier",
            )}
            type="number"
            min="0.0001"
            step="0.0001"
            value={form.operationalMultiplier}
            onChange={(event) =>
              setForm({ ...form, operationalMultiplier: event.target.value })
            }
          />
          <Input
            label={tr(
              t,
              "billing.catalog.customPlans.vendorRates.variabilityReserve",
              "Variability reserve",
            )}
            type="number"
            min="1"
            step="0.01"
            value={form.variabilityReserve}
            onChange={(event) =>
              setForm({ ...form, variabilityReserve: event.target.value })
            }
          />
          <Select
            label={tr(t, "billing.catalog.fields.status", "Status")}
            value={form.verificationStatus}
            onChange={(event) =>
              setForm({ ...form, verificationStatus: event.target.value })
            }
            options={[
              "confirmed",
              "estimated",
              "unconfirmed",
              "deprecated",
            ].map((value) => ({
              value,
              label: tr(
                t,
                `billing.catalog.customPlans.vendorRates.status.${value}`,
                value,
              ),
            }))}
          />
          <Input
            label={tr(
              t,
              "billing.catalog.customPlans.vendorRates.source",
              "Source / evidence",
            )}
            value={form.source}
            onChange={(event) =>
              setForm({ ...form, source: event.target.value })
            }
            required
          />
        </div>
        {error && <p className="billing-inline-error">{error}</p>}
      </form>
    </Modal>
  );
}

export function CustomPlanPricingPolicyPanel({ t, features = [], api = billingApi, canManagePricing = true }) {
  const {
    data: response,
    error,
    isLoading,
    mutate,
  } = useSWR(
    "custom-plan-pricing-policy",
    api.getCustomPlanPricingPolicy,
    swrOptions,
  );
  const policy = response?.data;
  const [form, setForm] = useState(null);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState(null);

  const [confirmation, setConfirmation] = useState(null);
  useEffect(() => {
    if (!policy) return;
    const value = (v, fallback) => policy.versioned ? (v ?? '') : fallback;
    setForm({
      currency: policy.currency ?? 'USD',
      targetGrossMarginPercent: policy.targetGrossMargin == null ? '' : Number(policy.targetGrossMargin) * 100,
      fixedPlatformFee: value(policy.fixedPlatformFee, policy.fixedPlatformFee ?? 0),
      monthlyInfrastructureCost: value(policy.monthlyInfrastructureCost, policy.monthlyInfrastructureCost ?? 0),
      activePayingTenants: value(policy.activePayingTenants, policy.activePayingTenants ?? 1),
      estimatedOtherCost: value(undefined, policy.estimatedOtherCost ?? 0),
      roundingIncrement: value(policy.roundingIncrement, policy.roundingIncrement ?? 1),
      maxAutomaticMonthlyPrice: value(undefined, policy.maxAutomaticMonthlyPrice ?? 2500),
      maxAutomaticQuotaPerFeature: value(undefined, policy.maxAutomaticQuotaPerFeature ?? 500000),
      enforceVendorCostRatioFloor: Boolean(policy.enforceVendorCostRatioFloor),
      maxVendorCostRevenueRatioPercent: policy.maxVendorCostRevenueRatio == null ? '' : Number(policy.maxVendorCostRevenueRatio) * 100,
      featureLimits: policy.featureLimits ?? {}, approvalEvidence: '',
    });
  }, [policy]);

  if (error && isForbiddenBillingError(error)) {
    return (
      <section className="billing-catalog-section">
        <h2>
          {tr(
            t,
            "billing.catalog.customPlans.pricingPolicy.title",
            "Automated Custom Pricing Policy",
          )}
        </h2>
        <p className="billing-catalog-permission-note">
          {tr(
            t,
            "billing.catalog.customPlans.pricingPolicy.permission",
            "Pricing policy requires the strongest owner permission because it controls internal margins and costs.",
          )}
        </p>
      </section>
    );
  }

  if (error) return <section className="billing-catalog-section"><p role="alert" className="billing-inline-error">{getApiError(error).message}</p><Button onClick={() => mutate()}>{tr(t, 'common.retry', 'Retry')}</Button></section>;
  if (isLoading || !form)
    return (
      <section className="billing-catalog-section">
        <Skeleton height="180px" variant="rectangular" />
      </section>
    );

  const save = async () => {
    setSaving(true);
    setMessage(null);
    try {
      if (policy.versioned) {
        await api.updateCustomPlanPricingPolicy({
          currency: form.currency,
          targetGrossMargin: form.targetGrossMarginPercent === '' ? '' : Number(form.targetGrossMarginPercent) / 100,
          maxVendorCostRevenueRatio: form.maxVendorCostRevenueRatioPercent === '' ? null : Number(form.maxVendorCostRevenueRatioPercent) / 100,
          fixedPlatformFee: form.fixedPlatformFee, monthlyInfrastructureCost: form.monthlyInfrastructureCost,
          activePayingTenants: form.activePayingTenants, roundingIncrement: form.roundingIncrement,
          enforceVendorCostRatioFloor: form.enforceVendorCostRatioFloor, approvalEvidence: form.approvalEvidence,
        });
      } else {
      await api.updateCustomPlanPricingPolicy({
        currency: String(form.currency || "JOD").toUpperCase(),
        targetGrossMargin: numeric(form.targetGrossMarginPercent) / 100,
        fixedPlatformFee: numeric(form.fixedPlatformFee),
        monthlyInfrastructureCost: numeric(form.monthlyInfrastructureCost),
        activePayingTenants: Math.max(
          1,
          Math.trunc(numeric(form.activePayingTenants, 1)),
        ),
        estimatedOtherCost: numeric(form.estimatedOtherCost),
        roundingIncrement: numeric(form.roundingIncrement),
        maxAutomaticMonthlyPrice: numeric(form.maxAutomaticMonthlyPrice),
        maxAutomaticQuotaPerFeature: Math.max(
          1,
          Math.trunc(numeric(form.maxAutomaticQuotaPerFeature, 1)),
        ),
        enforceVendorCostRatioFloor: Boolean(form.enforceVendorCostRatioFloor),
        maxVendorCostRevenueRatio:
          numeric(form.maxVendorCostRevenueRatioPercent) / 100,
        featureLimits: Object.fromEntries(
          Object.entries(form.featureLimits || {}).map(([code, limits]) => [
            code,
            {
              ...(limits.min !== "" && limits.min != null
                ? { min: Math.max(0, Math.trunc(numeric(limits.min))) }
                : {}),
              ...(limits.max !== "" && limits.max != null
                ? { max: Math.max(1, Math.trunc(numeric(limits.max, 1))) }
                : {}),
              ...(limits.step !== "" && limits.step != null
                ? { step: Math.max(1, Math.trunc(numeric(limits.step, 1))) }
                : {}),
            },
          ]),
        ),
      });
      }
      await mutate();
      setMessage({
        variant: "success",
        text: policy.versioned ? tr(t, "billing.catalog.legacyRestoration.draftSaved", "New draft saved. Existing approved quotes are unchanged.") : tr(t, "billing.catalog.customPlans.pricingPolicy.saved", "Automated custom-plan pricing policy saved."),
      });
    } catch (requestError) {
      setMessage({ variant: "error", text: getApiError(requestError).message });
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="billing-catalog-section">
      <div className="billing-catalog-section-heading">
        <div>
          <h2>
            {tr(
              t,
              "billing.catalog.customPlans.pricingPolicy.title",
              "Automated Custom Pricing Policy",
            )}
          </h2>
          <p>
            {tr(
              t,
              "billing.catalog.customPlans.pricingPolicy.subtitle",
              "Internal-only inputs used by self-service previews and recalculated again at checkout. Vendor-cost ratio enforcement is optional.",
            )}
          </p>
        </div>
        <Button size="sm" onClick={() => policy.versioned ? setConfirmation({kind:"save"}) : save()} loading={saving} disabled={!canManagePricing}>
          {tr(
            t,
            "billing.catalog.customPlans.pricingPolicy.save",
            "Save policy",
          )}
        </Button>
      </div>
      {policy.versioned && <>
        <p className="billing-catalog-permission-note">{tr(t, 'billing.catalog.legacyRestoration.versionedPolicy', 'Save creates a new draft revision. Activation requires explicit evidence. Instant-approval thresholds, per-feature bounds and other estimated costs remain policy-gated; no financial defaults are seeded.')}</p>
        <Input label={tr(t, 'billing.catalog.legacyRestoration.approvalEvidence', 'Approval evidence / rationale')} value={form.approvalEvidence} onChange={e => setForm({...form, approvalEvidence:e.target.value})} required />
        <Table data={policy.policies || []} columns={[
          {header:tr(t,'billing.catalog.legacyRestoration.version','Version'),accessor:'version_number'},
          {header:tr(t,'billing.catalog.fields.status','Status'),accessor:'status'},
          {header:tr(t,'billing.catalog.legacyRestoration.effectiveFrom','Effective from'),render:p=>p.effective_from || '\u2014'},
          {header:tr(t,'billing.catalog.actions','Actions'),render:p=>p.status==='draft' && <Button size="sm" disabled={!canManagePricing} onClick={()=>setConfirmation({kind:'activate',id:p.policy_version_id})}>{tr(t,'billing.catalog.legacyRestoration.activate','Activate')}</Button>},
        ]} />
        <Modal isOpen={Boolean(confirmation)} onClose={saving ? undefined : ()=>setConfirmation(null)} title={tr(t,'billing.catalog.legacyRestoration.confirmPolicy','Confirm pricing policy action')} footer={<><Button variant="outline" disabled={saving} onClick={()=>setConfirmation(null)}>{tr(t,'common.cancel','Cancel')}</Button><Button loading={saving} onClick={async()=>{
          const selected=confirmation; setConfirmation(null);
          if(selected.kind==='save') return save();
          setSaving(true); setMessage(null);
          try {
            if(!form.approvalEvidence.trim()) throw new Error(tr(t,'billing.catalog.legacyRestoration.evidenceRequired','Approval evidence is required.'));
            await api.activateCustomPlanPricingPolicy(selected.id,form.approvalEvidence.trim()); await mutate();
            setMessage({variant:'success',text:tr(t,'billing.catalog.legacyRestoration.activated','Policy activated for future calculations. Approved quote snapshots remain frozen.')});
          } catch(e) {setMessage({variant:'error',text:getApiError(e).message});} finally {setSaving(false);}
        }}>{tr(t,'common.confirm','Confirm')}</Button></>}>
          <p>{tr(t,'billing.catalog.legacyRestoration.policyConfirmation','A draft does not change customer rights. Activation affects future quote calculations; it does not alter approved quotes, subscriptions or credit budgets.')}</p>
        </Modal>
      </>}
      <div className="billing-catalog-form-grid">
        <Input
          label={tr(t, "billing.catalog.fields.currency", "Currency")}
          maxLength={3}
          value={form.currency} disabled={policy.versioned}
          onChange={(event) =>
            setForm({ ...form, currency: event.target.value })
          }
        />
        <Input
          label={tr(
            t,
            "billing.catalog.customPlans.targetMargin",
            "Target gross margin %",
          )}
          type="number"
          min="0"
          max="99.99"
          step="0.1"
          value={form.targetGrossMarginPercent}
          onChange={(event) =>
            setForm({ ...form, targetGrossMarginPercent: event.target.value })
          }
        />
        <Input
          label={tr(
            t,
            "billing.catalog.customPlans.pricingPolicy.fixedPlatformFee",
            "Fixed platform fee",
          )}
          type="number"
          min="0"
          step="0.01"
          value={form.fixedPlatformFee}
          onChange={(event) =>
            setForm({ ...form, fixedPlatformFee: event.target.value })
          }
        />
        <Input
          label={tr(
            t,
            "billing.catalog.customPlans.pricingPolicy.monthlyInfrastructure",
            "Monthly shared infrastructure",
          )}
          type="number"
          min="0"
          step="0.01"
          value={form.monthlyInfrastructureCost}
          onChange={(event) =>
            setForm({ ...form, monthlyInfrastructureCost: event.target.value })
          }
        />
        <Input
          label={tr(
            t,
            "billing.catalog.customPlans.activeTenants",
            "Active paying tenants",
          )}
          type="number"
          min="1"
          step="1"
          value={form.activePayingTenants}
          onChange={(event) =>
            setForm({ ...form, activePayingTenants: event.target.value })
          }
        />
        <Input
          label={tr(
            t,
            "billing.catalog.customPlans.pricingPolicy.otherEstimatedCostPerTenant",
            "Other estimated cost / tenant",
          )}
          type="number"
          min="0"
          step="0.01"
          value={form.estimatedOtherCost} disabled={policy.versioned}
          onChange={(event) =>
            setForm({ ...form, estimatedOtherCost: event.target.value })
          }
        />
        <Input
          label={tr(
            t,
            "billing.catalog.customPlans.pricingPolicy.roundingIncrement",
            "Round price up to increment",
          )}
          type="number"
          min="0"
          step="0.01"
          value={form.roundingIncrement}
          onChange={(event) =>
            setForm({ ...form, roundingIncrement: event.target.value })
          }
        />
        <Input
          label={tr(
            t,
            "billing.catalog.customPlans.pricingPolicy.maxAutomaticMonthlyPrice",
            "Maximum instant monthly price",
          )}
          type="number"
          min="0.01"
          step="0.01"
          value={form.maxAutomaticMonthlyPrice} disabled={policy.versioned}
          onChange={(event) =>
            setForm({ ...form, maxAutomaticMonthlyPrice: event.target.value })
          }
        />
        <Input
          label={tr(
            t,
            "billing.catalog.customPlans.pricingPolicy.maxAutomaticQuotaPerFeature",
            "Default max instant quota / feature",
          )}
          type="number"
          min="1"
          step="1"
          value={form.maxAutomaticQuotaPerFeature} disabled={policy.versioned}
          onChange={(event) =>
            setForm({
              ...form,
              maxAutomaticQuotaPerFeature: event.target.value,
            })
          }
        />
        <Input
          label={tr(
            t,
            "billing.catalog.customPlans.pricingPolicy.vendorCostRevenueThreshold",
            "Vendor cost/revenue threshold %",
          )}
          type="number"
          min="0.01"
          max="100"
          step="0.1"
          value={form.maxVendorCostRevenueRatioPercent}
          onChange={(event) =>
            setForm({
              ...form,
              maxVendorCostRevenueRatioPercent: event.target.value,
            })
          }
        />
      </div>
      <Checkbox
        checked={form.enforceVendorCostRatioFloor}
        onChange={(event) =>
          setForm({
            ...form,
            enforceVendorCostRatioFloor: event.target.checked,
          })
        }
        label={tr(
          t,
          "billing.catalog.customPlans.pricingPolicy.enforceVendorCostRatioFloor",
          "Enforce vendor-cost/revenue floor before sale (optional conservative guardrail)",
        )}
      />
      {features.some((feature) => feature.type === "limit") && (
        <div className="billing-catalog-form">
          <h3>
            {tr(
              t,
              "billing.catalog.customPlans.pricingPolicy.featureLimitsTitle",
              "Per-feature instant-checkout limits",
            )}
          </h3>
          <p className="ceopro-preview-notice">
            {tr(
              t,
              "billing.catalog.customPlans.pricingPolicy.featureLimitsHelp",
              "Leave a value blank to use the global default. Requests above a configured maximum become manual-review quotes instead of failing.",
            )}
          </p>
          <fieldset disabled={policy.versioned} className="billing-catalog-form-grid">
            {features
              .filter((feature) => feature.type === "limit")
              .map((feature) => {
                const limits = form.featureLimits?.[feature.code] ?? {};
                const updateLimit = (field, value) =>
                  setForm((current) => ({
                    ...current,
                    featureLimits: {
                      ...(current.featureLimits || {}),
                      [feature.code]: {
                        ...(current.featureLimits?.[feature.code] || {}),
                        [field]: value,
                      },
                    },
                  }));
                return (
                  <Card
                    key={feature.id}
                    className="billing-custom-plan-price-summary"
                  >
                    <strong>{feature.name}</strong>
                    <Input
                      label={tr(
                        t,
                        "billing.catalog.customPlans.pricingPolicy.minimum",
                        "Minimum",
                      )}
                      type="number"
                      min="0"
                      step="1"
                      value={limits.min ?? ""}
                      onChange={(event) =>
                        updateLimit("min", event.target.value)
                      }
                    />
                    <Input
                      label={tr(
                        t,
                        "billing.catalog.customPlans.pricingPolicy.maximum",
                        "Maximum",
                      )}
                      type="number"
                      min="1"
                      step="1"
                      value={limits.max ?? ""}
                      onChange={(event) =>
                        updateLimit("max", event.target.value)
                      }
                    />
                    <Input
                      label={tr(
                        t,
                        "billing.catalog.customPlans.pricingPolicy.step",
                        "Step",
                      )}
                      type="number"
                      min="1"
                      step="1"
                      value={limits.step ?? ""}
                      onChange={(event) =>
                        updateLimit("step", event.target.value)
                      }
                    />
                  </Card>
                );
              })}
          </fieldset>
        </div>
      )}
      {message && (
        <p
          className={
            message.variant === "error"
              ? "billing-inline-error"
              : "ceopro-preview-notice"
          }
        >
          {message.text}
        </p>
      )}
    </section>
  );
}

export default function CustomPlanQuoteManager({ features, t, locale, api = billingApi, platformMode = false, canManage = true, canManagePricing = true }) {
  const [reviewQuote, setReviewQuote] = useState(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [editQuote, setEditQuote] = useState(null);
  const [approveQuote, setApproveQuote] = useState(null);
  const [vendorRateOpen, setVendorRateOpen] = useState(false);
  const [editRate, setEditRate] = useState(null);
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState(null);

  const { data: tenantsResponse } = useSWR(
    platformMode ? "platform-billing-tenants" : null,
    platformMode && api.getTenants ? api.getTenants : null,
    swrOptions,
  );
  const tenants = tenantsResponse?.data ?? [];

  const { data: pricingPolicyResponse } = useSWR(
    "custom-plan-pricing-policy",
    api.getCustomPlanPricingPolicy,
    swrOptions,
  );
  const monitoringCadences =
    pricingPolicyResponse?.data?.monitoringCadences ?? [];

  const {
    data: quotesResponse,
    error: quotesError,
    isLoading: quotesLoading,
    mutate: mutateQuotes,
  } = useSWR(platformMode ? "platform-custom-plan-quotes" : "custom-plan-quotes", api.getCustomPlanQuotes, swrOptions);
  const {
    data: ratesResponse,
    error: ratesError,
    isLoading: ratesLoading,
    mutate: mutateRates,
  } = useSWR(platformMode ? "platform-custom-plan-vendor-rates" : "custom-plan-vendor-rates", api.getVendorRates, swrOptions);
  const quotes = quotesResponse?.data ?? [];
  const rates = ratesResponse?.data ?? [];
  const ratesForbidden = ratesError && isForbiddenBillingError(ratesError);

  const run = useCallback(async (key, action, successMessage) => {
    setBusy(key);
    setNotice(null);
    try {
      await action();
      await mutateQuotes();
      setNotice({ variant: "success", message: successMessage });
    } catch (requestError) {
      setNotice({
        variant: "error",
        message: getApiError(requestError).message,
      });
    } finally {
      setBusy("");
    }
  }, [mutateQuotes]);

  const columns = useMemo(
    () => [
      {
        header: tr(t, "billing.catalog.fields.name", "Name"),
        render: (quote) =>
          locale === "ar" && quote.nameAr ? quote.nameAr : quote.name,
      },
      ...(platformMode
        ? [{
            header: tr(
              t,
              "billing.catalog.customPlans.tenant",
              "Customer tenant",
            ),
            render: (quote) => quote.tenant?.businessName ?? quote.tenantId ?? "—",
          }]
        : []),
      ...(platformMode ? [{
        header: tr(t, "billing.catalog.customPlans.configuration", "Requested configuration"),
        render: (quote) => <details><summary>{tr(t, "billing.catalog.fields.details", "Details")}</summary><pre className="billing-custom-plan-configuration">{JSON.stringify({ configuration: quote.configuration || {}, quantities: quote.quantities || {} }, null, 2)}</pre></details>,
      }] : []),
      {
        header: tr(t, "billing.catalog.fields.status", "Status"),
        render: (quote) => (
          <Badge variant={statusVariant(quote.status)}>
            {tr(
              t,
              `billing.catalog.customPlans.status.${quote.status}`,
              quote.status,
            )}
          </Badge>
        ),
      },
      {
        header: tr(
          t,
          "billing.catalog.customPlans.estimatedTotal",
          "Estimated cost",
        ),
        render: (quote) =>
          money(quote.estimatedTotalCost, quote.currency, locale),
      },
      {
        header: tr(
          t,
          "billing.catalog.customPlans.minimumSafePrice",
          "Minimum safe price",
        ),
        render: (quote) =>
          money(quote.minimumSafePrice, quote.currency, locale),
      },
      {
        header: tr(
          t,
          "billing.catalog.customPlans.recommendedPrice",
          "Recommended price",
        ),
        render: (quote) =>
          money(quote.recommendedPrice, quote.currency, locale),
      },
      {
        header: tr(
          t,
          "billing.catalog.customPlans.finalPrice",
          "Final customer price",
        ),
        render: (quote) => money(quote.finalPrice, quote.currency, locale),
      },
      {
        header: tr(t, "billing.catalog.actions", "Actions"),
        render: (quote) => (
          <div className="billing-catalog-row-actions billing-custom-plan-actions">
            {platformMode && <Button variant="outline" size="sm" onClick={()=>setReviewQuote(quote)}>{tr(t,"billing.catalog.customPlans.review","Review")}</Button>}
            {canManage && ["draft", "calculated", "submitted"].includes(quote.status) && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => setEditQuote(quote)}
              >
                {tr(t, "common.edit", "Edit")}
              </Button>
            )}
            {canManage && ["draft", "calculated", "submitted"].includes(quote.status) && (
              <Button
                variant="outline"
                size="sm"
                loading={busy === `calc-${quote.id}`}
                onClick={() =>
                  run(
                    `calc-${quote.id}`,
                    () => api.calculateCustomPlanQuote(quote.id),
                    tr(
                      t,
                      "billing.catalog.customPlans.calculated",
                      "Pricing recalculated.",
                    ),
                  )
                }
                leadingIcon={<RefreshCw size={13} />}
              >
                {tr(t, "billing.catalog.customPlans.calculate", "Calculate")}
              </Button>
            )}
            {canManage && (quote.status === "calculated" || (platformMode && quote.status === "submitted" && quote.pricingAvailable)) && (
              <Button size="sm" onClick={() => setApproveQuote(quote)}>
                {tr(t, "billing.catalog.customPlans.approve", "Approve")}
              </Button>
            )}
            {canManage && quote.status === "approved" && (
              <Button
                size="sm"
                loading={busy === `send-${quote.id}`}
                onClick={() =>
                  run(
                    `send-${quote.id}`,
                    () => api.sendCustomPlanQuote(quote.id),
                    tr(
                      t,
                      "billing.catalog.customPlans.inAppOfferAvailable",
                      "The approved offer is available in the customer portal.",
                    ),
                  )
                }
              >
                  {tr(t, "billing.catalog.customPlans.inAppOfferAvailable", "Available in customer portal")}
              </Button>
            )}
            {canManage && ["submitted", "approved", "sent"].includes(quote.status) && (
              <Button
                variant="ghost"
                size="sm"
                loading={busy === `reject-${quote.id}`}
                onClick={() =>
                  run(
                    `reject-${quote.id}`,
                    () => api.rejectCustomPlanQuote(quote.id),
                    tr(
                      t,
                      "billing.catalog.customPlans.rejected",
                      "Quote rejected.",
                    ),
                  )
                }
              >
                {tr(t, "billing.catalog.customPlans.reject", "Reject")}
              </Button>
            )}
            {!platformMode && ["approved", "sent", "accepted"].includes(quote.status) && (
              <Link
                className="billing-link-button billing-custom-plan-offer-link"
                to={routePaths.customPlanOffer.replace(":quoteId", quote.id)}
              >
                <ExternalLink size={13} />
                {tr(t, "billing.catalog.customPlans.openOffer", "Offer")}
              </Link>
            )}
          </div>
        ),
      },
    ],
    [busy, locale, t, canManage, platformMode, api, run],
  );

  const rateColumns = [
    {
      header: tr(t, "billing.catalog.customPlans.vendorRates.vendor", "Vendor"),
      accessor: "vendor",
    },
    {
      header: tr(
        t,
        "billing.catalog.customPlans.vendorRates.service",
        "Service",
      ),
      accessor: "service",
    },
    {
      header: tr(t, "billing.catalog.fields.feature", "Feature"),
      render: (rate) => rate.feature?.name ?? "—",
    },
    {
      header: tr(
        t,
        "billing.catalog.customPlans.vendorRates.unitCost",
        "Unit cost",
      ),
      render: (rate) => money(rate.unitCost, rate.currency, locale),
    },
    {
      header: tr(
        t,
        "billing.catalog.customPlans.vendorRates.unit",
        "Billing unit",
      ),
      accessor: "billingUnit",
    },
    {
      header: tr(
        t,
        "billing.catalog.customPlans.vendorRates.usageAssumption",
        "Usage assumption",
      ),
      render: (rate) => {
        const assumption = rate.metadata?.usageAssumption;
        if (assumption?.model !== "competitor_monitoring") return "—";
        return tr(
          t,
          "billing.catalog.customPlans.vendorRates.perCompetitorCheck",
          "{{units}} {{unit}} per competitor check",
          {
            units: assumption.unitsPerCompetitorCheck,
            unit: rate.billingUnit,
          },
        );
      },
    },
    {
      header: tr(t, "billing.catalog.fields.status", "Status"),
      render: (rate) => (
        <Badge
          variant={
            rate.verificationStatus === "confirmed"
              ? "success"
              : rate.verificationStatus === "deprecated"
                ? "error"
                : "warning"
          }
        >
          {tr(
            t,
            `billing.catalog.customPlans.vendorRates.status.${rate.verificationStatus}`,
            rate.verificationStatus,
          )}
        </Badge>
      ),
    },
    ...(canManagePricing
      ? [
          {
            header: tr(t, "billing.catalog.actions", "Actions"),
            render: (rate) => (
              <Button
                variant="outline"
                size="sm"
                onClick={() => setEditRate(rate)}
              >
                {tr(t, "common.edit", "Edit")}
              </Button>
            ),
          },
        ]
      : []),
  ];

  if (quotesError && isForbiddenBillingError(quotesError)) {
    return (
      <EmptyState
        title={tr(
          t,
          "billing.catalog.permissions.title",
          "Catalog access unavailable",
        )}
        description={tr(
          t,
          "billing.catalog.permissions.catalogRequired",
          "This area requires catalog management permission.",
        )}
      />
    );
  }

  return (
    <div className="billing-custom-plan-manager">
      <CustomPlanPricingPolicyPanel t={t} features={features} api={api} canManagePricing={canManagePricing} />

      <section className="billing-catalog-section">
        <div className="billing-catalog-section-heading">
          <div>
            <h2>
              {tr(t, "billing.catalog.customPlans.title", "Custom Plan Quotes")}
            </h2>
            <p>
              {tr(
                t,
                "billing.catalog.customPlans.subtitle",
                "Build tenant-private offers. Backend pricing is authoritative; accepted offers become normal plans.",
              )}
            </p>
          </div>
          <Button
            size="sm"
            leadingIcon={<Plus size={14} />}
            onClick={() => setCreateOpen(true)} disabled={!canManage}
          >
            {tr(t, "billing.catalog.customPlans.create", "Create Quote")}
          </Button>
        </div>
        {quotesLoading ? (
          <Skeleton height="220px" variant="rectangular" />
        ) : quotesError ? (
          <p className="billing-inline-error">
            {getApiError(quotesError).message}
          </p>
        ) : quotes.length ? (
          <Table
            data={quotes}
            columns={columns}
            ariaLabel={tr(
              t,
              "billing.catalog.customPlans.title",
              "Custom Plan Quotes",
            )}
          />
        ) : (
          <EmptyState
            title={tr(
              t,
              "billing.catalog.customPlans.emptyTitle",
              "No custom quotes yet",
            )}
            description={tr(
              t,
              "billing.catalog.customPlans.emptyDescription",
              "Create a quote to calculate cost-aware pricing for this tenant.",
            )}
          />
        )}
      </section>

      <section className="billing-catalog-section billing-custom-plan-rate-section">
        <div className="billing-catalog-section-heading">
          <div>
            <h2>
              {tr(
                t,
                "billing.catalog.customPlans.vendorRates.title",
                "Vendor Rate Cards",
              )}
            </h2>
            <p>
              {tr(
                t,
                "billing.catalog.customPlans.vendorRates.subtitle",
                "Internal cost inputs used by the backend pricing service. These are never customer prices.",
              )}
            </p>
          </div>
          {!ratesForbidden && (
            <Button
              variant="outline"
              size="sm"
              leadingIcon={<Plus size={14} />}
              onClick={() => setVendorRateOpen(true)} disabled={!canManagePricing}
            >
              {tr(
                t,
                "billing.catalog.customPlans.vendorRates.create",
                "Add vendor rate",
              )}
            </Button>
          )}
        </div>
        {ratesForbidden ? (
          <p className="billing-catalog-permission-note">
            {tr(
              t,
              "billing.catalog.customPlans.vendorRates.permission",
              "Vendor rates require the strongest catalog permission because they are global internal cost inputs.",
            )}
          </p>
        ) : ratesLoading ? (
          <Skeleton height="180px" variant="rectangular" />
        ) : ratesError ? (
          <p className="billing-inline-error">
            {getApiError(ratesError).message}
          </p>
        ) : (
          <Table
            data={rates}
            columns={rateColumns}
            ariaLabel={tr(
              t,
              "billing.catalog.customPlans.vendorRates.title",
              "Vendor Rate Cards",
            )}
          />
        )}
      </section>

      {platformMode && api.getInfrastructureRates && (
        <InfrastructureRateCards
          features={features}
          t={t}
          locale={locale}
          api={api}
          canManagePricing={canManagePricing}
        />
      )}

      <QuoteFormModal
        open={createOpen || Boolean(editQuote)}
        quote={editQuote}
        onClose={() => {
          setCreateOpen(false);
          setEditQuote(null);
        }}
        features={features}
        api={api}
        platformMode={platformMode}
        tenants={tenants}
        monitoringCadences={monitoringCadences}
        onSaved={async(result)=>{
          await mutateQuotes();
          if(result?.pricingError) setNotice({variant:'warning',message:`${tr(t,'billing.catalog.legacyRestoration.requestSaved','Request saved for review.')} ${result.pricingError}`});
        }}
        t={t}
        locale={locale}
      />
      <QuoteReviewModal quote={reviewQuote} onClose={()=>setReviewQuote(null)} api={api} t={t} locale={locale} />
      <ApproveQuoteModal
        quote={approveQuote}
        onClose={() => setApproveQuote(null)}
        onApproved={mutateQuotes}
        platformMode={platformMode}
        t={t}
        locale={locale}
        api={api}
      />
      <VendorRateModal
        open={vendorRateOpen || Boolean(editRate)}
        rate={editRate}
        onClose={() => {
          setVendorRateOpen(false);
          setEditRate(null);
        }}
        features={features}
        api={api}
        onSaved={mutateRates}
        t={t}
      />
      {notice && (
        <div className="billing-catalog-inline-toast">
          <Toast
            variant={notice.variant}
            message={notice.message}
            onClose={() => setNotice(null)}
          />
        </div>
      )}
    </div>
  );
}
