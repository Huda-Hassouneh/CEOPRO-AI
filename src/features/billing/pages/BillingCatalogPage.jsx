import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, Link2, Pencil, Plus, Save } from "lucide-react";
import { useNavigate } from "react-router-dom";
import useSWR from "swr";
import { useI18n } from "../../../app/providers/I18nProvider.jsx";
import { routePaths } from "../../../app/router/routePaths.js";
import PageHeader from "../../../shared/components/layout/PageHeader.jsx";
import Badge from "../../../shared/components/ui/Badge.jsx";
import Button from "../../../shared/components/ui/Button.jsx";
import Card from "../../../shared/components/ui/Card.jsx";
import EmptyState from "../../../shared/components/ui/EmptyState.jsx";
import Input from "../../../shared/components/ui/Input.jsx";
import Modal from "../../../shared/components/ui/Modal.jsx";
import Select from "../../../shared/components/ui/Select.jsx";
import Skeleton from "../../../shared/components/ui/Skeleton.jsx";
import Table from "../../../shared/components/ui/Table.jsx";
import Tabs from "../../../shared/components/ui/Tabs.jsx";
import Toast from "../../../shared/components/ui/Toast.jsx";
import CustomPlanQuoteManager from "../components/CustomPlanQuoteManager.jsx";
import BillingOptionsEditor from "../components/BillingOptionsEditor.jsx";
import {
  billingApi,
  getApiError,
  isForbiddenBillingError
} from "../api/billingApi.js";
import "../styles/Billing.css";
import "../styles/PlansSubscription.css";

const swrOptions = { shouldRetryOnError: false, revalidateOnFocus: false };
const DEFAULT_BILLING_OPTIONS = [
  { period: "monthly", months: 1, discountPercent: 0 },
  { period: "three-months", months: 3, discountPercent: 10 },
  { period: "six-months", months: 6, discountPercent: 20 }
];

const toNumber = (value, fallback = 0) => {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
};

const toDateTimeLocal = (value) => {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
};

const toIsoDate = (value) =>
  value ? new Date(value).toISOString() : undefined;

function SectionError({ error }) {
  if (!error) return null;
  return <p className="billing-inline-error">{getApiError(error).message}</p>;
}

function PlanFormModal({ isOpen, onClose, plan, onSaved, t, api = billingApi }) {
  const editing = Boolean(plan);
  const [form, setForm] = useState(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!isOpen) return;
    setError("");
    setForm({
      name: plan?.name ?? "",
      name_ar: plan?.name_ar ?? "",
      tierLevel: plan?.tier_level ?? 1,
      description: plan?.description ?? "",
      description_ar: plan?.description_ar ?? "",
      price: plan?.basePrice ?? 0,
      currency: plan?.currency ?? "JOD",
      billingIntervalValue: 1,
      billingIntervalUnit: "month",
      trialPeriodValue: plan?.trialPeriodValue ?? 0,
      billingOptions: plan?.pricingOptions?.length
        ? plan.pricingOptions.map(({ period, months, discountPercent }) => ({
            period,
            months,
            discountPercent
          }))
        : DEFAULT_BILLING_OPTIONS
    });
  }, [isOpen, plan]);

  if (!form) return null;

  const validate = () => {
    if (!form.name.trim() || !form.name_ar.trim())
      return t("billing.catalog.validation.planNames");
    if (
      !Number.isInteger(toNumber(form.tierLevel)) ||
      toNumber(form.tierLevel) <= 0
    )
      return t("billing.catalog.validation.tier");
    if (toNumber(form.price, -1) < 0)
      return t("billing.catalog.validation.price");
    if (!/^[A-Z]{3}$/.test(form.currency.trim().toUpperCase()))
      return t("billing.catalog.validation.currency");
    if (!form.billingOptions.length)
      return t("billing.catalog.validation.billingOptions");
    for (const option of form.billingOptions) {
      if (
        !option.period.trim() ||
        !Number.isInteger(toNumber(option.months)) ||
        toNumber(option.months) <= 0
      )
        return t("billing.catalog.validation.billingOption");
      if (
        toNumber(option.discountPercent, -1) < 0 ||
        toNumber(option.discountPercent) > 100
      )
        return t("billing.catalog.validation.discount");
    }
    return "";
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    const validationError = validate();
    if (validationError) {
      setError(validationError);
      return;
    }

    const common = {
      name: form.name.trim(),
      name_ar: form.name_ar.trim(),
      tierLevel: toNumber(form.tierLevel),
      description: form.description.trim() || undefined,
      description_ar: form.description_ar.trim() || undefined,
      price: toNumber(form.price),
      currency: form.currency.trim().toUpperCase(),
      trialPeriodValue: toNumber(form.trialPeriodValue),
      billingOptions: form.billingOptions.map((option) => ({
        period: option.period.trim(),
        months: toNumber(option.months),
        discountPercent: toNumber(option.discountPercent)
      }))
    };

    const payload = editing
      ? common
      : {
          ...common,
          billingIntervalValue: toNumber(form.billingIntervalValue),
          billingIntervalUnit: form.billingIntervalUnit,
          isActive: true
        };

    setSaving(true);
    setError("");
    try {
      if (editing) await api.updatePlan(plan.id, payload);
      else await api.createPlan(payload);
      await onSaved();
      onClose();
    } catch (requestError) {
      setError(getApiError(requestError).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={saving ? undefined : onClose}
      title={
        editing
          ? t("billing.catalog.plans.editTitle")
          : t("billing.catalog.plans.createTitle")
      }
      maxWidth="760px"
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={saving}>
            {t("common.cancel")}
          </Button>
          <Button type="submit" form="billing-plan-form" loading={saving}>
            {t("common.save")}
          </Button>
        </>
      }
    >
      <form
        id="billing-plan-form"
        className="billing-catalog-form"
        onSubmit={handleSubmit}
      >
        <div className="billing-catalog-form-grid">
          <Input
            label={t("billing.catalog.fields.name")}
            value={form.name}
            onChange={(event) => setForm({ ...form, name: event.target.value })}
            maxLength={50}
            required
          />
          <Input
            label={t("billing.catalog.fields.nameAr")}
            value={form.name_ar}
            onChange={(event) =>
              setForm({ ...form, name_ar: event.target.value })
            }
            maxLength={50}
            required
            dir="rtl"
          />
          <Input
            label={t("billing.catalog.fields.tier")}
            type="number"
            min="1"
            step="1"
            value={form.tierLevel}
            onChange={(event) =>
              setForm({ ...form, tierLevel: event.target.value })
            }
            required
          />
          <Input
            label={t("billing.catalog.fields.price")}
            type="number"
            min="0"
            step="0.01"
            value={form.price}
            onChange={(event) =>
              setForm({ ...form, price: event.target.value })
            }
            required
          />
          <Input
            label={t("billing.catalog.fields.currency")}
            value={form.currency}
            maxLength={3}
            onChange={(event) =>
              setForm({ ...form, currency: event.target.value.toUpperCase() })
            }
            required
          />
          <Input
            label={t("billing.catalog.fields.trialDays")}
            type="number"
            min="0"
            step="1"
            value={form.trialPeriodValue}
            onChange={(event) =>
              setForm({ ...form, trialPeriodValue: event.target.value })
            }
            required
          />
          {!editing && (
            <>
              <Input
                label={t("billing.catalog.fields.intervalValue")}
                type="number"
                min="1"
                step="1"
                value={form.billingIntervalValue}
                onChange={(event) =>
                  setForm({ ...form, billingIntervalValue: event.target.value })
                }
                required
              />
              <Select
                label={t("billing.catalog.fields.intervalUnit")}
                value={form.billingIntervalUnit}
                onChange={(event) =>
                  setForm({ ...form, billingIntervalUnit: event.target.value })
                }
                options={["day", "week", "month", "year"].map((value) => ({
                  value,
                  label: t(`billing.catalog.intervalUnits.${value}`)
                }))}
              />
            </>
          )}
        </div>
        <div className="billing-catalog-textarea-grid">
          <label className="billing-catalog-textarea-field">
            <span className="ceopro-label">
              {t("billing.catalog.fields.description")}
            </span>
            <textarea
              value={form.description}
              onChange={(event) =>
                setForm({ ...form, description: event.target.value })
              }
              rows="3"
            />
          </label>
          <label className="billing-catalog-textarea-field">
            <span className="ceopro-label">
              {t("billing.catalog.fields.descriptionAr")}
            </span>
            <textarea
              value={form.description_ar}
              onChange={(event) =>
                setForm({ ...form, description_ar: event.target.value })
              }
              rows="3"
              dir="rtl"
            />
          </label>
        </div>

        <BillingOptionsEditor
          options={form.billingOptions}
          onChange={(billingOptions) => setForm({ ...form, billingOptions })}
          t={t}
        />
        {error && <p className="billing-inline-error">{error}</p>}
      </form>
    </Modal>
  );
}

function PromoFormModal({ isOpen, onClose, promo, onSaved, t, api = billingApi }) {
  const editing = Boolean(promo);
  const [form, setForm] = useState(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!isOpen) return;
    const now = new Date();
    const nextMonth = new Date(now.getTime() + 30 * 24 * 60 * 60 * 1000);
    setError("");
    setForm({
      code: promo?.code ?? "",
      discountType: promo?.discountType ?? "percentage",
      discountValue: promo?.discountValue ?? 10,
      maxUses: promo?.maxUses ?? 100,
      maxUsesPerUser: promo?.maxUsesPerUser ?? 1,
      startsAt: toDateTimeLocal(promo?.startsAt ?? now),
      expiresAt: toDateTimeLocal(promo?.expiresAt ?? nextMonth),
      isActive: promo?.isActive ?? true
    });
  }, [isOpen, promo]);

  if (!form) return null;

  const handleSubmit = async (event) => {
    event.preventDefault();
    const startsAt = toIsoDate(form.startsAt);
    const expiresAt = toIsoDate(form.expiresAt);
    if (!form.code.trim())
      return setError(t("billing.catalog.validation.promoCode"));
    if (
      toNumber(form.discountValue) <= 0 ||
      (form.discountType === "percentage" && toNumber(form.discountValue) > 100)
    )
      return setError(t("billing.catalog.validation.discount"));
    if (
      toNumber(form.maxUses) <= 0 ||
      toNumber(form.maxUsesPerUser) <= 0 ||
      toNumber(form.maxUsesPerUser) > toNumber(form.maxUses)
    )
      return setError(t("billing.catalog.validation.usageLimits"));
    if (!startsAt || !expiresAt || new Date(expiresAt) <= new Date(startsAt))
      return setError(t("billing.catalog.validation.dates"));

    setSaving(true);
    setError("");
    try {
      const payload = {
        code: form.code.trim().toUpperCase(),
        discountType: form.discountType,
        discountValue: toNumber(form.discountValue),
        maxUses: toNumber(form.maxUses),
        maxUsesPerUser: toNumber(form.maxUsesPerUser),
        startsAt,
        expiresAt,
        isActive: Boolean(form.isActive)
      };
      if (editing) await api.updatePromoCode(promo.id, payload);
      else await api.createPromoCode(payload);
      await onSaved();
      onClose();
    } catch (requestError) {
      setError(getApiError(requestError).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={saving ? undefined : onClose}
      title={
        editing
          ? t("billing.catalog.promos.editTitle")
          : t("billing.catalog.promos.createTitle")
      }
      maxWidth="650px"
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={saving}>
            {t("common.cancel")}
          </Button>
          <Button type="submit" form="billing-promo-form" loading={saving}>
            {t("common.save")}
          </Button>
        </>
      }
    >
      <form
        id="billing-promo-form"
        className="billing-catalog-form"
        onSubmit={handleSubmit}
      >
        <div className="billing-catalog-form-grid">
          <Input
            label={t("billing.catalog.fields.code")}
            value={form.code}
            onChange={(event) =>
              setForm({ ...form, code: event.target.value.toUpperCase() })
            }
            maxLength={50}
            required
          />
          <Select
            label={t("billing.catalog.fields.discountType")}
            value={form.discountType}
            onChange={(event) =>
              setForm({ ...form, discountType: event.target.value })
            }
            options={[
              {
                value: "percentage",
                label: t("billing.catalog.discountTypes.percentage")
              },
              {
                value: "fixed_amount",
                label: t("billing.catalog.discountTypes.fixedAmount")
              }
            ]}
          />
          <Input
            label={t("billing.catalog.fields.discountValue")}
            type="number"
            min="0.01"
            step="0.01"
            value={form.discountValue}
            onChange={(event) =>
              setForm({ ...form, discountValue: event.target.value })
            }
            required
          />
          <Input
            label={t("billing.catalog.fields.maxUses")}
            type="number"
            min="1"
            step="1"
            value={form.maxUses}
            onChange={(event) =>
              setForm({ ...form, maxUses: event.target.value })
            }
            required
          />
          <Input
            label={t("billing.catalog.fields.maxUsesPerUser")}
            type="number"
            min="1"
            step="1"
            value={form.maxUsesPerUser}
            onChange={(event) =>
              setForm({ ...form, maxUsesPerUser: event.target.value })
            }
            required
          />
          <Select
            label={t("billing.catalog.fields.status")}
            value={String(form.isActive)}
            onChange={(event) =>
              setForm({ ...form, isActive: event.target.value === "true" })
            }
            options={[
              { value: "true", label: t("billing.catalog.status.active") },
              { value: "false", label: t("billing.catalog.status.inactive") }
            ]}
          />
          <Input
            label={t("billing.catalog.fields.startsAt")}
            type="datetime-local"
            value={form.startsAt}
            onChange={(event) =>
              setForm({ ...form, startsAt: event.target.value })
            }
            required
          />
          <Input
            label={t("billing.catalog.fields.expiresAt")}
            type="datetime-local"
            value={form.expiresAt}
            onChange={(event) =>
              setForm({ ...form, expiresAt: event.target.value })
            }
            required
          />
        </div>
        {error && <p className="billing-inline-error">{error}</p>}
      </form>
    </Modal>
  );
}

function PromoLinkModal({ isOpen, onClose, promo, plans, onLinked, t, api = billingApi }) {
  const [planId, setPlanId] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!isOpen) return;
    setPlanId(plans[0]?.id ?? "");
    setError("");
  }, [isOpen, plans]);

  const submit = async () => {
    if (!promo || !planId) return;
    setSaving(true);
    setError("");
    try {
      await api.linkPromoCodeToPlan({ promoCodeId: promo.id, planId });
      onLinked();
      onClose();
    } catch (requestError) {
      setError(getApiError(requestError).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={saving ? undefined : onClose}
      title={t("billing.catalog.promos.linkTitle")}
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={saving}>
            {t("common.cancel")}
          </Button>
          <Button onClick={submit} loading={saving} disabled={!planId}>
            {t("billing.catalog.promos.linkAction")}
          </Button>
        </>
      }
    >
      <p className="billing-catalog-modal-copy">
        {t("billing.catalog.promos.linkHelp", { code: promo?.code ?? "" })}
      </p>
      <Select
        value={planId}
        onChange={(event) => setPlanId(event.target.value)}
        label={t("billing.catalog.fields.plan")}
        options={plans.map((plan) => ({ value: plan.id, label: plan.name }))}
      />
      {error && <p className="billing-inline-error">{error}</p>}
    </Modal>
  );
}

function FeatureFormModal({ isOpen, onClose, feature, onSaved, t, api = billingApi }) {
  const editing = Boolean(feature);
  const [form, setForm] = useState(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!isOpen) return;
    setError("");
    setForm({
      code: feature?.code ?? "",
      name: feature?.name ?? "",
      name_ar: feature?.name_ar ?? "",
      description: feature?.description ?? "",
      description_ar: feature?.description_ar ?? "",
      type: feature?.type ?? "limit",
      unit: feature?.unit ?? "",
      unit_ar: feature?.unit_ar ?? "",
      aggregation_type:
        feature?.aggregationType ?? feature?.aggregation_type ?? "sum",
      reset_cycle:
        feature?.resetCycle ?? feature?.reset_cycle ?? "billing_period"
    });
  }, [isOpen, feature]);

  if (!form) return null;

  const handleSubmit = async (event) => {
    event.preventDefault();
    if (!form.name.trim() || (!editing && !form.name_ar.trim()))
      return setError(t("billing.catalog.validation.featureNames"));
    if (!editing && !/^[a-z0-9_]{3,50}$/.test(form.code))
      return setError(t("billing.catalog.validation.featureCode"));

    setSaving(true);
    setError("");
    try {
      const metadata = form.type === "limit"
        ? {
            unit: form.unit.trim() || null,
            unit_ar: form.unit_ar.trim() || null,
            aggregation_type: form.aggregation_type,
            reset_cycle: form.reset_cycle
          }
        : {
            unit: undefined,
            unit_ar: undefined,
            aggregation_type: "sum",
            reset_cycle: "lifetime"
          };

      if (editing) {
        await api.updateFeature(feature.id, {
          name: form.name.trim(),
          name_ar: form.name_ar.trim(),
          description: form.description.trim() || null,
          description_ar: form.description_ar.trim() || null,
          type: form.type,
          ...metadata
        });
      } else {
        await api.createFeature({
          code: form.code.trim(),
          name: form.name.trim(),
          name_ar: form.name_ar.trim(),
          description: form.description.trim() || null,
          description_ar: form.description_ar.trim() || null,
          type: form.type,
          ...metadata
        });
      }
      await onSaved();
      onClose();
    } catch (requestError) {
      setError(getApiError(requestError).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={saving ? undefined : onClose}
      title={
        editing
          ? t("billing.catalog.features.editTitle")
          : t("billing.catalog.features.createTitle")
      }
      maxWidth="650px"
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={saving}>
            {t("common.cancel")}
          </Button>
          <Button type="submit" form="billing-feature-form" loading={saving}>
            {t("common.save")}
          </Button>
        </>
      }
    >
      <form
        id="billing-feature-form"
        className="billing-catalog-form"
        onSubmit={handleSubmit}
      >
        <div className="billing-catalog-form-grid">
          {!editing && (
            <Input
              label={t("billing.catalog.fields.featureCode")}
              value={form.code}
              onChange={(event) =>
                setForm({ ...form, code: event.target.value.toLowerCase() })
              }
              required
            />
          )}
          <Input
            label={t("billing.catalog.fields.name")}
            value={form.name}
            onChange={(event) => setForm({ ...form, name: event.target.value })}
            required
          />
          <Input
            label={t("billing.catalog.fields.nameAr")}
            value={form.name_ar}
            onChange={(event) =>
              setForm({ ...form, name_ar: event.target.value })
            }
            dir="rtl"
            required
          />
          <Select
            label={t("billing.catalog.fields.type")}
            value={form.type}
            onChange={(event) => setForm({ ...form, type: event.target.value })}
            options={[
              {
                value: "boolean",
                label: t("billing.catalog.featureTypes.boolean")
              },
              { value: "limit", label: t("billing.catalog.featureTypes.limit") }
            ]}
          />
          {form.type === "limit" && (
            <>
              <Input
                label={t("billing.catalog.fields.unit")}
                value={form.unit}
                onChange={(event) =>
                  setForm({ ...form, unit: event.target.value })
                }
              />
              <Input
                label={t("billing.catalog.fields.unitAr")}
                value={form.unit_ar}
                onChange={(event) =>
                  setForm({ ...form, unit_ar: event.target.value })
                }
                dir="rtl"
              />
              <Select
                label={t("billing.catalog.fields.aggregation")}
                value={form.aggregation_type}
                onChange={(event) => {
                  const aggregation_type = event.target.value;
                  setForm({
                    ...form,
                    aggregation_type,
                    reset_cycle: aggregation_type === "max" ? "lifetime" : form.reset_cycle
                  });
                }}
                options={[
                  { value: "sum", label: t("billing.catalog.aggregation.sum") },
                  { value: "max", label: t("billing.catalog.aggregation.max") }
                ]}
              />
              <Select
                label={t("billing.catalog.fields.resetCycle")}
                value={form.reset_cycle}
                disabled={form.aggregation_type === "max"}
                onChange={(event) =>
                  setForm({ ...form, reset_cycle: event.target.value })
                }
                options={[
                  {
                    value: "billing_period",
                    label: t("billing.catalog.resetCycles.billingPeriod")
                  },
                  {
                    value: "lifetime",
                    label: t("billing.catalog.resetCycles.lifetime")
                  }
                ]}
              />
            </>
          )}
        </div>
        <div className="billing-catalog-textarea-grid">
          <label className="billing-catalog-textarea-field">
            <span className="ceopro-label">
              {t("billing.catalog.fields.description")}
            </span>
            <textarea
              value={form.description}
              onChange={(event) =>
                setForm({ ...form, description: event.target.value })
              }
              rows="3"
            />
          </label>
          <label className="billing-catalog-textarea-field">
            <span className="ceopro-label">
              {t("billing.catalog.fields.descriptionAr")}
            </span>
            <textarea
              value={form.description_ar}
              onChange={(event) =>
                setForm({ ...form, description_ar: event.target.value })
              }
              rows="3"
              dir="rtl"
            />
          </label>
        </div>
        {error && <p className="billing-inline-error">{error}</p>}
      </form>
    </Modal>
  );
}

function PlanFeatureManager({ plans, features, t, locale, api = billingApi, canManage = true }) {
  const [planId, setPlanId] = useState(plans[0]?.id ?? "");
  const [featureId, setFeatureId] = useState("");
  const [newLimit, setNewLimit] = useState("");
  const [limitDrafts, setLimitDrafts] = useState({});
  const [busyKey, setBusyKey] = useState("");
  const [notice, setNotice] = useState(null);

  useEffect(() => {
    if (!plans.some((plan) => plan.id === planId))
      setPlanId(plans[0]?.id ?? "");
  }, [plans, planId]);

  const {
    data: linksResponse,
    error,
    isLoading,
    mutate
  } = useSWR(
    planId ? ["billing-plan-features", planId] : null,
    () => api.getPlanFeatures(planId),
    swrOptions
  );
  const links = linksResponse?.data ?? [];
  const linkedIds = new Set(links.map((link) => link.feature_id));
  const available = features.filter((feature) => !linkedIds.has(feature.id));
  const selectedFeature = features.find((feature) => feature.id === featureId);

  useEffect(() => {
    if (!available.some((feature) => feature.id === featureId))
      setFeatureId(available[0]?.id ?? "");
  }, [featureId, linksResponse, features]);

  const linkFeature = async () => {
    if (!planId || !featureId) return;
    setBusyKey("link");
    setNotice(null);
    try {
      await api.linkFeatureToPlan(planId, {
        feature_id: featureId,
        limit_value:
          selectedFeature?.type === "boolean" || newLimit === ""
            ? null
            : toNumber(newLimit)
      });
      setNewLimit("");
      await mutate();
      setNotice({
        variant: "success",
        message: t("billing.catalog.planFeatures.linked")
      });
    } catch (requestError) {
      setNotice({
        variant: "error",
        message: getApiError(requestError).message
      });
    } finally {
      setBusyKey("");
    }
  };

  const updateLimit = async (link) => {
    const feature = link.feature;
    const draft = limitDrafts[link.feature_id] ?? link.limit_value ?? "";
    setBusyKey(link.feature_id);
    setNotice(null);
    try {
      await api.updatePlanFeatureLimit({
        planId,
        featureId: link.feature_id,
        limitValue:
          feature?.type === "boolean" || draft === "" ? null : toNumber(draft)
      });
      await mutate();
      setNotice({
        variant: "success",
        message: t("billing.catalog.planFeatures.updated")
      });
    } catch (requestError) {
      setNotice({
        variant: "error",
        message: getApiError(requestError).message
      });
    } finally {
      setBusyKey("");
    }
  };

  if (!plans.length)
    return (
      <EmptyState
        title={t("billing.catalog.plans.emptyTitle")}
        description={t("billing.catalog.plans.emptyDescription")}
      />
    );

  return (
    <div className="billing-catalog-plan-features">
      <Card className="billing-catalog-toolbar">
        <Select
          label={t("billing.catalog.fields.plan")}
          value={planId}
          onChange={(event) => setPlanId(event.target.value)}
          options={plans.map((plan) => ({
            value: plan.id,
            label: locale === "ar" && plan.name_ar ? plan.name_ar : plan.name
          }))}
        />
        {canManage && (
          <>
            <Select
              label={t("billing.catalog.fields.feature")}
              value={featureId}
              onChange={(event) => setFeatureId(event.target.value)}
              options={
                available.length
                  ? available.map((feature) => ({
                      value: feature.id,
                      label:
                        locale === "ar" && feature.name_ar
                          ? feature.name_ar
                          : feature.name
                    }))
                  : [
                      {
                        value: "",
                        label: t("billing.catalog.planFeatures.noAvailable")
                      }
                    ]
              }
              disabled={!available.length}
            />
            <Input
              label={t("billing.catalog.fields.limit")}
              type="number"
              min="0"
              step="1"
              value={newLimit}
              disabled={!selectedFeature || selectedFeature.type === "boolean"}
              onChange={(event) => setNewLimit(event.target.value)}
              placeholder={
                selectedFeature?.type === "boolean"
                  ? t("billing.catalog.planFeatures.notApplicable")
                  : ""
              }
            />
            <Button
              onClick={linkFeature}
              loading={busyKey === "link"}
              disabled={
                !featureId ||
                (selectedFeature?.type !== "boolean" &&
                  newLimit !== "" &&
                  toNumber(newLimit, -1) < 0)
              }
              leadingIcon={<Link2 size={14} />}
            >
              {t("billing.catalog.planFeatures.link")}
            </Button>
          </>
        )}
      </Card>

      {isLoading ? (
        <Skeleton height="180px" variant="rectangular" />
      ) : error ? (
        <SectionError error={error} />
      ) : (
        <Table
          ariaLabel={t("billing.catalog.planFeatures.title")}
          data={links}
          columns={[
            {
              header: t("billing.catalog.fields.feature"),
              render: (link) =>
                locale === "ar" && link.feature?.name_ar
                  ? link.feature.name_ar
                  : (link.feature?.name ?? link.feature_id)
            },
            {
              header: t("billing.catalog.fields.type"),
              render: (link) =>
                t(
                  `billing.catalog.featureTypes.${link.feature?.type ?? "limit"}`
                )
            },
            {
              header: t("billing.catalog.fields.limit"),
              render: (link) =>
                link.feature?.type === "boolean" ? (
                  t("billing.catalog.planFeatures.notApplicable")
                ) : (
                  <input
                    className="billing-catalog-inline-input"
                    type="number"
                    min="0"
                    step="1"
                    value={
                      limitDrafts[link.feature_id] ?? link.limit_value ?? ""
                    }
                    disabled={!canManage}
                    onChange={(event) =>
                      setLimitDrafts((current) => ({
                        ...current,
                        [link.feature_id]: event.target.value
                      }))
                    }
                  />
                )
            },
            {
              header: t("billing.catalog.actions"),
              render: (link) =>
                canManage ? (
                  <Button
                    variant="outline"
                    size="sm"
                    loading={busyKey === link.feature_id}
                    onClick={() => updateLimit(link)}
                    leadingIcon={<Save size={13} />}
                  >
                    {t("common.save")}
                  </Button>
                ) : (
                  <span className="billing-catalog-read-only">{t("billing.catalog.readOnly")}</span>
                )
            }
          ]}
        />
      )}
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


function PlatformCustomPlansManager({ api, t, locale, canManage }) {
  const { data: response, error, isLoading, mutate } = useSWR(
    "platform-custom-plans",
    api.getCustomPlans,
    swrOptions
  );
  const [target, setTarget] = useState(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState(null);
  const plans = response?.data ?? [];
  const tt = (key, fallback) => {
    const value = t(key);
    return value === key ? fallback : value;
  };

  const toggleStatus = async () => {
    if (!target) return;
    setBusy(true);
    setNotice(null);
    try {
      await api.setCustomPlanActive(target.id, !target.isActive);
      await mutate();
      setNotice({
        variant: "success",
        message: target.isActive
          ? "Custom plan disabled. The tenant subscription, accepted quote, price, and limits were not changed."
          : "Custom plan enabled."
      });
      setTarget(null);
    } catch (requestError) {
      setNotice({ variant: "error", message: getApiError(requestError).message });
    } finally {
      setBusy(false);
    }
  };

  if (isLoading) return <Skeleton height="220px" variant="rectangular" />;
  if (error) return <SectionError error={error} />;

  return (
    <section className="billing-catalog-section">
      <div className="billing-catalog-section-heading">
        <div>
          <h2>{tt("billing.catalog.customPlans.acceptedTitle", "Accepted Custom Plans")}</h2>
          <p>{tt("billing.catalog.customPlans.acceptedSubtitle", "Accepted quotes become immutable tenant-specific plan definitions. Enabled does not mean the tenant is currently subscribed; the subscription relationship is shown separately.")}</p>
        </div>
      </div>
      {plans.length ? (
        <Table
          data={plans}
          ariaLabel="Accepted custom plans"
          columns={[
            {
              header: "Tenant",
              render: (plan) => plan.tenant?.businessName ?? plan.tenantId ?? "—"
            },
            {
              header: tt("billing.catalog.fields.name", "Name"),
              render: (plan) => locale === "ar" && plan.name_ar ? plan.name_ar : plan.name
            },
            {
              header: tt("billing.catalog.fields.price", "Price"),
              render: (plan) => new Intl.NumberFormat(locale, {
                style: "currency",
                currency: /^[A-Z]{3}$/.test(plan.currency ?? "") ? plan.currency : "USD",
                maximumFractionDigits: 2
              }).format(plan.basePrice ?? 0)
            },
            {
              header: "Plan state",
              render: (plan) => (
                <Badge variant={plan.isActive ? "success" : "neutral"}>
                  {plan.isActive ? "Enabled" : "Disabled"}
                </Badge>
              )
            },
            {
              header: "Subscription relationship",
              render: (plan) => {
                const relationship = plan.subscriptionRelationship ?? "not_subscribed";
                const label = relationship === "current"
                  ? "Current"
                  : relationship === "scheduled"
                    ? "Scheduled"
                    : "Not subscribed";
                const variant = relationship === "current"
                  ? "success"
                  : relationship === "scheduled"
                    ? "warning"
                    : "neutral";
                const currentPlan = plan.scheduledSubscription?.currentPlan;
                const currentPlanName = currentPlan
                  ? (locale === "ar" && currentPlan.name_ar ? currentPlan.name_ar : currentPlan.name)
                  : null;
                return (
                  <div style={{ display: "grid", gap: "4px" }}>
                    <Badge variant={variant}>{label}</Badge>
                    {relationship === "scheduled" && currentPlanName ? (
                      <small style={{ color: "var(--ceopro-text-muted)" }}>
                        Current: {currentPlanName}
                      </small>
                    ) : null}
                  </div>
                );
              }
            },
            {
              header: "Effective date",
              render: (plan) => plan.subscriptionEffectiveAt
                ? new Intl.DateTimeFormat(locale, { dateStyle: "medium" }).format(new Date(plan.subscriptionEffectiveAt))
                : "—"
            },
            {
              header: "Source quote",
              render: (plan) => plan.sourceQuote?.id ? plan.sourceQuote.id.slice(0, 8) : "—"
            },
            {
              header: tt("billing.catalog.actions", "Actions"),
              render: (plan) => canManage ? (
                <div className="billing-catalog-row-actions">
                  <Button variant="outline" size="sm" onClick={() => setTarget(plan)}>
                    {plan.isActive ? "Disable" : "Enable"}
                  </Button>
                  <span className="billing-catalog-read-only">Commercial terms are immutable</span>
                </div>
              ) : (
                <span className="billing-catalog-read-only">{tt("billing.catalog.readOnly", "Read only")}</span>
              )
            }
          ]}
        />
      ) : (
        <EmptyState
          title="No accepted custom plans"
          description="Accepted custom quotes will appear here as tenant-specific plans."
        />
      )}
      <Modal
        isOpen={Boolean(target)}
        onClose={busy ? undefined : () => setTarget(null)}
        title={target?.isActive ? "Disable custom plan" : "Enable custom plan"}
        footer={
          <>
            <Button variant="outline" onClick={() => setTarget(null)} disabled={busy}>Cancel</Button>
            <Button onClick={toggleStatus} loading={busy}>{target?.isActive ? "Disable" : "Enable"}</Button>
          </>
        }
      >
        <p>
          This changes only whether the custom plan definition is enabled for use. It does not change which plan the tenant is currently subscribed to, and the accepted quote, price, limits, and other commercial terms remain unchanged.
        </p>
      </Modal>
      {notice && (
        <div className="billing-catalog-inline-toast">
          <Toast variant={notice.variant} message={notice.message} onClose={() => setNotice(null)} />
        </div>
      )}
    </section>
  );
}

function PlatformSubscriptionsManager({ api, t, locale }) {
  const { data: response, error, isLoading } = useSWR(
    "platform-billing-subscriptions",
    api.getSubscriptions,
    swrOptions
  );
  const subscriptions = response?.data ?? [];
  const tt = (key, fallback) => {
    const value = t(key);
    return value === key ? fallback : value;
  };
  const date = (value) => value ? new Intl.DateTimeFormat(locale, { dateStyle: "medium" }).format(new Date(value)) : "—";

  if (isLoading) return <Skeleton height="220px" variant="rectangular" />;
  if (error) return <SectionError error={error} />;

  return (
    <section className="billing-catalog-section">
      <div className="billing-catalog-section-heading">
        <div>
          <h2>Customer Subscriptions</h2>
          <p>Platform-level view of tenant subscriptions. This is not the platform owner's own subscription.</p>
        </div>
      </div>
      {subscriptions.length ? (
        <Table
          data={subscriptions}
          ariaLabel="Customer subscriptions"
          columns={[
            { header: "Tenant", render: (row) => row.tenant?.businessName ?? row.tenantId },
            {
              header: "Current plan",
              render: (row) => locale === "ar" && row.plan?.name_ar
                ? row.plan.name_ar
                : row.plan?.name ?? row.planId
            },
            { header: tt("billing.catalog.fields.status", "Status"), render: (row) => <Badge variant={["active", "trialing", "trial"].includes(row.status) ? "success" : "neutral"}>{row.status}</Badge> },
            {
              header: "Scheduled change",
              render: (row) => row.scheduledPlan ? (
                <div style={{ display: "grid", gap: "4px" }}>
                  <Badge variant="warning">Scheduled</Badge>
                  <span>
                    {locale === "ar" && row.scheduledPlan?.name_ar
                      ? row.scheduledPlan.name_ar
                      : row.scheduledPlan?.name}
                  </span>
                </div>
              ) : "—"
            },
            {
              header: "Transition",
              render: (row) => row.transitionType ? (
                <Badge variant={row.transitionType === "upgrade" ? "success" : row.transitionType === "mixed" ? "warning" : "neutral"}>
                  {row.transitionType.charAt(0).toUpperCase() + row.transitionType.slice(1)}
                </Badge>
              ) : "—"
            },
            { header: "Effective date", render: (row) => date(row.scheduledEffectiveAt) },
            { header: "Billing period", accessor: "billingPeriod" },
            { header: "Current period end", render: (row) => date(row.currentPeriodEnd) },
            { header: "Cancel at period end", render: (row) => row.cancelAtPeriodEnd ? "Yes" : "No" }
          ]}
        />
      ) : (
        <EmptyState title="No subscriptions" description="Customer subscriptions will appear here." />
      )}
    </section>
  );
}

export function BillingCatalogPage({ api = billingApi, platformMode = false, canManage = true, canManagePricing = true }) {
  const { t, locale, dir } = useI18n();
  const navigate = useNavigate();
  const [planModal, setPlanModal] = useState({ open: false, plan: null });
  const [promoModal, setPromoModal] = useState({ open: false, promo: null });
  const [promoLinkModal, setPromoLinkModal] = useState({
    open: false,
    promo: null
  });
  const [featureModal, setFeatureModal] = useState({
    open: false,
    feature: null
  });
  const [notice, setNotice] = useState(null);
  const [planStatusTarget, setPlanStatusTarget] = useState(null);
  const [planStatusBusy, setPlanStatusBusy] = useState(false);

  const {
    data: plansResponse,
    error: plansError,
    isLoading: plansLoading,
    mutate: mutatePlans
  } = useSWR(platformMode ? "platform-billing-plans" : "subscription-plans", api.getPlans, swrOptions);
  const {
    data: featuresResponse,
    error: featuresError,
    isLoading: featuresLoading,
    mutate: mutateFeatures
  } = useSWR(
    platformMode ? "platform-billing-features" : "subscription-catalog-features",
    api.getFeatures,
    swrOptions
  );
  const {
    data: promosResponse,
    error: promosError,
    isLoading: promosLoading,
    mutate: mutatePromos
  } = useSWR(
    platformMode ? "platform-billing-promos" : "subscription-catalog-promos",
    api.getPromoCodes,
    swrOptions
  );

  const plans = plansResponse?.data ?? [];
  const features = featuresResponse?.data ?? [];
  const promos = promosResponse?.data ?? [];
  const canManageCatalog = platformMode ? canManage : Boolean(featuresResponse) && !featuresError;
  const canManageAll = platformMode ? canManage : Boolean(promosResponse) && !promosError;
  const featuresForbidden =
    featuresError && isForbiddenBillingError(featuresError);
  const promosForbidden = promosError && isForbiddenBillingError(promosError);
  const isOwnerCatalogUser = Boolean(promosResponse) && !promosError;
  const dateFormatter = useMemo(
    () => new Intl.DateTimeFormat(locale, { dateStyle: "medium" }),
    [locale]
  );
  const moneyFormatter = (currency) =>
    new Intl.NumberFormat(locale, {
      style: "currency",
      currency: /^[A-Z]{3}$/.test(currency ?? "") ? currency : "USD",
      maximumFractionDigits: 2
    });

  const showNotice = (message) => setNotice({ variant: "success", message });

  const planColumns = [
    {
      header: t("billing.catalog.fields.name"),
      render: (plan) =>
        locale === "ar" && plan.name_ar ? plan.name_ar : plan.name
    },
    { header: t("billing.catalog.fields.tier"), accessor: "tier_level" },
    {
      header: t("billing.catalog.fields.price"),
      render: (plan) =>
        moneyFormatter(plan.currency).format(plan.basePrice ?? 0)
    },
    {
      header: t("billing.catalog.fields.billingOptions"),
      render: (plan) => plan.pricingOptions?.length ?? 0
    },
    {
      header: t("billing.catalog.fields.trialDays"),
      accessor: "trialPeriodValue"
    },
    {
      header: t("billing.catalog.fields.status"),
      render: (plan) => <Badge variant={plan.isActive ? "success" : "neutral"}>{plan.isActive ? "Active" : "Inactive"}</Badge>
    },
    {
      header: t("billing.catalog.actions"),
      render: (plan) =>
        canManageAll ? (
          <div className="billing-catalog-row-actions">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setPlanModal({ open: true, plan })}
              leadingIcon={<Pencil size={13} />}
            >
              {t("common.edit")}
            </Button>
            {platformMode && (
              <Button variant="outline" size="sm" onClick={() => setPlanStatusTarget(plan)}>
                {plan.isActive ? "Deactivate" : "Activate"}
              </Button>
            )}
          </div>
        ) : (
          <span className="billing-catalog-read-only">
            {t("billing.catalog.readOnly")}
          </span>
        )
    }
  ];

  const promoColumns = [
    { header: t("billing.catalog.fields.code"), accessor: "code" },
    {
      header: t("billing.catalog.fields.discount"),
      render: (promo) =>
        promo.discountType === "percentage"
          ? `${promo.discountValue}%`
          : String(promo.discountValue)
    },
    {
      header: t("billing.catalog.fields.usage"),
      render: (promo) => `${promo.usedCount ?? 0} / ${promo.maxUses}`
    },
    {
      header: t("billing.catalog.fields.expiresAt"),
      render: (promo) =>
        promo.expiresAt ? dateFormatter.format(new Date(promo.expiresAt)) : "—"
    },
    {
      header: t("billing.catalog.fields.status"),
      render: (promo) =>
        promo.isActive
          ? t("billing.catalog.status.active")
          : t("billing.catalog.status.inactive")
    },
    {
      header: t("billing.catalog.actions"),
      render: (promo) => canManageAll ? (
        <div className="billing-catalog-row-actions">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setPromoModal({ open: true, promo })}
            leadingIcon={<Pencil size={13} />}
          >
            {t("common.edit")}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setPromoLinkModal({ open: true, promo })}
            leadingIcon={<Link2 size={13} />}
          >
            {t("billing.catalog.promos.linkAction")}
          </Button>
        </div>
      ) : <span className="billing-catalog-read-only">{t("billing.catalog.readOnly")}</span>
    }
  ];

  const featureColumns = [
    { header: t("billing.catalog.fields.featureCode"), accessor: "code" },
    {
      header: t("billing.catalog.fields.name"),
      render: (feature) =>
        locale === "ar" && feature.name_ar ? feature.name_ar : feature.name
    },
    {
      header: t("billing.catalog.fields.type"),
      render: (feature) => t(`billing.catalog.featureTypes.${feature.type}`)
    },
    {
      header: t("billing.catalog.fields.unit"),
      render: (feature) => feature.unit || "—"
    },
    {
      header: t("billing.catalog.fields.resetCycle"),
      render: (feature) =>
        t(
          `billing.catalog.resetCycles.${feature.resetCycle ?? feature.reset_cycle ?? "billing_period"}`
        )
    },
    {
      header: t("billing.catalog.actions"),
      render: (feature) => canManageCatalog ? (
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setFeatureModal({ open: true, feature })}
          leadingIcon={<Pencil size={13} />}
        >
          {t("common.edit")}
        </Button>
      ) : <span className="billing-catalog-read-only">{t("billing.catalog.readOnly")}</span>
    }
  ];

  const plansContent = (
    <section className="billing-catalog-section">
      <div className="billing-catalog-section-heading">
        <div>
          <h2>{t("billing.catalog.plans.title")}</h2>
          <p>{t("billing.catalog.plans.subtitle")}</p>
        </div>
        {canManageAll && (
          <Button
            size="sm"
            leadingIcon={<Plus size={14} />}
            onClick={() => setPlanModal({ open: true, plan: null })}
          >
            {t("billing.catalog.plans.create")}
          </Button>
        )}
      </div>
      {plansLoading ? (
        <Skeleton height="220px" variant="rectangular" />
      ) : plansError ? (
        <SectionError error={plansError} />
      ) : (
        <Table
          data={plans}
          columns={planColumns}
          ariaLabel={t("billing.catalog.plans.title")}
        />
      )}
      {!canManageAll && promosForbidden && (
        <p className="billing-catalog-permission-note">
          {t("billing.catalog.permissions.planWrite")}
        </p>
      )}
    </section>
  );

  const promosContent = promosForbidden ? (
    <EmptyState
      title={t("billing.catalog.permissions.title")}
      description={t("billing.catalog.permissions.allRequired")}
    />
  ) : (
    <section className="billing-catalog-section">
      <div className="billing-catalog-section-heading">
        <div>
          <h2>{t("billing.catalog.promos.title")}</h2>
          <p>{t("billing.catalog.promos.subtitle")}</p>
        </div>
        {canManageAll && (
          <Button
            size="sm"
            leadingIcon={<Plus size={14} />}
            onClick={() => setPromoModal({ open: true, promo: null })}
          >
            {t("billing.catalog.promos.create")}
          </Button>
        )}
      </div>
      {promosLoading ? (
        <Skeleton height="220px" variant="rectangular" />
      ) : promosError ? (
        <SectionError error={promosError} />
      ) : (
        <Table
          data={promos}
          columns={promoColumns}
          ariaLabel={t("billing.catalog.promos.title")}
        />
      )}
    </section>
  );

  const featuresContent = featuresForbidden ? (
    <EmptyState
      title={t("billing.catalog.permissions.title")}
      description={t("billing.catalog.permissions.catalogRequired")}
    />
  ) : (
    <section className="billing-catalog-section">
      <div className="billing-catalog-section-heading">
        <div>
          <h2>{t("billing.catalog.features.title")}</h2>
          <p>{t("billing.catalog.features.subtitle")}</p>
        </div>
        {canManageCatalog && (
          <Button
            size="sm"
            leadingIcon={<Plus size={14} />}
            onClick={() => setFeatureModal({ open: true, feature: null })}
          >
            {t("billing.catalog.features.create")}
          </Button>
        )}
      </div>
      {featuresLoading ? (
        <Skeleton height="220px" variant="rectangular" />
      ) : featuresError ? (
        <SectionError error={featuresError} />
      ) : (
        <Table
          data={features}
          columns={featureColumns}
          ariaLabel={t("billing.catalog.features.title")}
        />
      )}
    </section>
  );

  const planFeaturesContent = featuresForbidden ? (
    <EmptyState
      title={t("billing.catalog.permissions.title")}
      description={t("billing.catalog.permissions.catalogRequired")}
    />
  ) : featuresLoading ? (
    <Skeleton height="220px" variant="rectangular" />
  ) : featuresError ? (
    <SectionError error={featuresError} />
  ) : (
    <section className="billing-catalog-section">
      <div className="billing-catalog-section-heading">
        <div>
          <h2>{t("billing.catalog.planFeatures.title")}</h2>
          <p>{t("billing.catalog.planFeatures.subtitle")}</p>
        </div>
      </div>
      <PlanFeatureManager
        plans={plans}
        features={features}
        t={t}
        locale={locale}
        api={api}
        canManage={canManageAll}
      />
    </section>
  );

  const customQuotesContent = featuresForbidden ? (
    <EmptyState
      title={t("billing.catalog.permissions.title")}
      description={t("billing.catalog.permissions.catalogRequired")}
    />
  ) : (
    <CustomPlanQuoteManager features={features} t={t} locale={locale} api={api} platformMode={platformMode} canManage={canManageAll} canManagePricing={canManagePricing} />
  );
  const customPlansContent = platformMode ? (
    <PlatformCustomPlansManager api={api} t={t} locale={locale} canManage={canManageAll} />
  ) : customQuotesContent;
  const subscriptionsContent = platformMode && api.getSubscriptions ? (
    <PlatformSubscriptionsManager api={api} t={t} locale={locale} />
  ) : null;
  if (promosForbidden) {
    return (
      <div className="billing-management-page billing-catalog-page" dir={dir}>
        <button
          className="billing-back-link billing-catalog-back"
          type="button"
          onClick={() => navigate(platformMode ? "/admin" : routePaths.billing)}
        >
          <ArrowLeft className="ceopro-setup-direction-icon" size={14} />{" "}
          {t("billing.catalog.back")}
        </button>

        <PageHeader
          title={t("billing.catalog.title")}
          subtitle={t("billing.catalog.subtitle")}
        />

        <EmptyState
          title={platformMode ? "Platform billing access required" : "Owner access required"}
          description={
            platformMode
              ? "Your platform role does not include access to billing administration."
              : "Catalog management is available only to the tenant owner."
          }
        />
      </div>
    );
  }
  return (
    <div className="billing-management-page billing-catalog-page" dir={dir}>
      <Tabs
        ariaLabel={t("billing.catalog.title")}
        tabs={[
          {
            id: "plans",
            label: t("billing.catalog.tabs.plans"),
            content: plansContent
          },
          {
            id: "custom-plans",
            label:
              t("billing.catalog.tabs.customPlans") ===
              "billing.catalog.tabs.customPlans"
                ? "Custom Plans"
                : t("billing.catalog.tabs.customPlans"),
            content: customPlansContent
          },
          ...(platformMode ? [{ id: "custom-quotes", label: "Custom Quotes", content: customQuotesContent }] : []),
          {
            id: "promos",
            label: t("billing.catalog.tabs.promos"),
            content: promosContent
          },
          {
            id: "features",
            label: t("billing.catalog.tabs.features"),
            content: featuresContent
          },
          {
            id: "plan-features",
            label: t("billing.catalog.tabs.planFeatures"),
            content: planFeaturesContent
          },
          ...(platformMode && subscriptionsContent ? [{ id: "subscriptions", label: "Subscriptions", content: subscriptionsContent }] : [])
        ]}
      />

      <PlanFormModal
        isOpen={planModal.open}
        onClose={() =>
          setPlanModal({
            open: false,
            plan: null
          })
        }
        plan={planModal.plan}
        t={t}
        api={api}
        onSaved={async () => {
          await mutatePlans();

          showNotice(
            planModal.plan
              ? t("billing.catalog.plans.updated")
              : t("billing.catalog.plans.created")
          );
        }}
      />

      <PromoFormModal
        isOpen={promoModal.open}
        onClose={() =>
          setPromoModal({
            open: false,
            promo: null
          })
        }
        promo={promoModal.promo}
        t={t}
        api={api}
        onSaved={async () => {
          await mutatePromos();

          showNotice(
            promoModal.promo
              ? t("billing.catalog.promos.updated")
              : t("billing.catalog.promos.created")
          );
        }}
      />

      <PromoLinkModal
        isOpen={promoLinkModal.open}
        onClose={() =>
          setPromoLinkModal({
            open: false,
            promo: null
          })
        }
        promo={promoLinkModal.promo}
        plans={plans}
        t={t}
        api={api}
        onLinked={() => showNotice(t("billing.catalog.promos.linked"))}
      />

      <FeatureFormModal
        isOpen={featureModal.open}
        onClose={() =>
          setFeatureModal({
            open: false,
            feature: null
          })
        }
        feature={featureModal.feature}
        t={t}
        api={api}
        onSaved={async () => {
          await mutateFeatures();

          showNotice(
            featureModal.feature
              ? t("billing.catalog.features.updated")
              : t("billing.catalog.features.created")
          );
        }}
      />

      <Modal
        isOpen={Boolean(planStatusTarget)}
        onClose={planStatusBusy ? undefined : () => setPlanStatusTarget(null)}
        title={planStatusTarget?.isActive ? "Deactivate standard plan" : "Activate standard plan"}
        footer={
          <>
            <Button variant="outline" onClick={() => setPlanStatusTarget(null)} disabled={planStatusBusy}>Cancel</Button>
            <Button
              loading={planStatusBusy}
              onClick={async () => {
                if (!planStatusTarget) return;
                setPlanStatusBusy(true);
                try {
                  await api.updatePlan(planStatusTarget.id, { isActive: !planStatusTarget.isActive });
                  await mutatePlans();
                  showNotice(planStatusTarget.isActive ? "Plan deactivated." : "Plan activated.");
                  setPlanStatusTarget(null);
                } catch (requestError) {
                  setNotice({ variant: "error", message: getApiError(requestError).message });
                } finally {
                  setPlanStatusBusy(false);
                }
              }}
            >
              {planStatusTarget?.isActive ? "Deactivate" : "Activate"}
            </Button>
          </>
        }
      >
        <p>{planStatusTarget?.isActive ? "The plan will remain visible in platform management but will no longer be offered to customers." : "The plan will become available in the customer plan catalog again."}</p>
      </Modal>

      {notice && (
        <div className="billing-management-toast">
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
