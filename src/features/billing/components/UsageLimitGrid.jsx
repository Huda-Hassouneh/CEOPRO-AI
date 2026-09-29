import {
  AlertTriangle,
  Bot,
  Check,
  Database,
  FileText,
  Gauge,
  HardDrive,
  Infinity as InfinityIcon,
  PackageCheck,
  Sparkles
} from "lucide-react";

import { getUsageState } from "../utils/subscriptionRecommendations.js";

function toFiniteNumber(value) {
  if (typeof value === "boolean" || value === null || value === undefined) {
    return null;
  }

  const parsed = Number(value);

  return Number.isFinite(parsed) ? parsed : null;
}

function getFeatureType(featureData, used, limit) {
  const declaredType = String(
    featureData?.type ??
      featureData?.value_type ??
      featureData?.valueType ??
      featureData?.limit_type ??
      ""
  ).toLowerCase();

  if (
    declaredType === "boolean" ||
    declaredType === "bool" ||
    typeof limit === "boolean" ||
    typeof used === "boolean"
  ) {
    return "boolean";
  }

  if (limit === null) {
    return "unlimited";
  }

  if (toFiniteNumber(limit) !== null) {
    return "limited";
  }

  return "unknown";
}

function getBooleanEnabled(used, limit) {
  if (typeof limit === "boolean") {
    return limit;
  }

  if (typeof used === "boolean") {
    return used;
  }

  return false;
}

function normalizeUnit(unit) {
  return String(unit || "")
    .trim()
    .toLowerCase();
}

function formatNumber(value, locale, maximumFractionDigits = 1) {
  return new Intl.NumberFormat(locale, {
    maximumFractionDigits
  }).format(value);
}

/*
 * Converts internal storage/billing units into something comfortable
 * for the customer to read.
 *
 * document_extraction:
 *   database = KB
 *   340   -> 340 KB
 *   2048  -> 2 MB
 *
 * document_storage_mb:
 *   database = MB
 *   5.9   -> 5.9 MB
 *   1536  -> 1.5 GB
 */
function formatMeasuredValue(value, unit, locale) {
  const numericValue = toFiniteNumber(value);

  if (numericValue === null) {
    return {
      value: "—",
      unit: unit || ""
    };
  }

  const normalizedUnit = normalizeUnit(unit);

  if (normalizedUnit === "kb") {
    if (numericValue >= 1024 * 1024) {
      return {
        value: formatNumber(numericValue / (1024 * 1024), locale, 2),
        unit: "GB"
      };
    }

    if (numericValue >= 1024) {
      return {
        value: formatNumber(numericValue / 1024, locale, 2),
        unit: "MB"
      };
    }

    return {
      value: formatNumber(numericValue, locale, 0),
      unit: "KB"
    };
  }

  if (normalizedUnit === "mb") {
    if (numericValue >= 1024) {
      return {
        value: formatNumber(numericValue / 1024, locale, 2),
        unit: "GB"
      };
    }

    return {
      value: formatNumber(numericValue, locale, 2),
      unit: "MB"
    };
  }

  if (normalizedUnit === "gb") {
    return {
      value: formatNumber(numericValue, locale, 2),
      unit: "GB"
    };
  }

  return {
    value: formatNumber(numericValue, locale, 1),
    unit: unit || ""
  };
}

function UsageValue({ value, unit, locale, className }) {
  const formatted = formatMeasuredValue(value, unit, locale);

  return (
    <bdi className={className}>
      <strong>{formatted.value} </strong>

      {formatted.unit && (
        <span className="billing-usage-value-unit">{formatted.unit}</span>
      )}
    </bdi>
  );
}

function getFeatureIcon(key) {
  const normalizedKey = String(key || "").toLowerCase();

  if (
    normalizedKey.includes("storage") ||
    normalizedKey.includes("document_storage")
  ) {
    return HardDrive;
  }

  if (
    normalizedKey.includes("document") ||
    normalizedKey.includes("extraction")
  ) {
    return FileText;
  }

  if (normalizedKey.includes("rag") || normalizedKey.includes("assistant")) {
    return Bot;
  }

  if (normalizedKey.includes("data") || normalizedKey.includes("source")) {
    return Database;
  }

  if (
    normalizedKey.includes("product") ||
    normalizedKey.includes("competitor")
  ) {
    return PackageCheck;
  }

  if (normalizedKey.includes("ai") || normalizedKey.includes("prediction")) {
    return Sparkles;
  }

  return Gauge;
}

function UsageCardHeader({ featureKey, label, description, status, state }) {
  const Icon = getFeatureIcon(featureKey);

  return (
    <div className="billing-usage-card__header">
      <div className="billing-usage-card__identity">
        <span className="billing-usage-card__icon" aria-hidden="true">
          <Icon size={19} strokeWidth={1.9} />
        </span>

        <div className="billing-usage-card__copy">
          <strong className="billing-usage-card__title">{label}</strong>

          {description && (
            <p className="billing-usage-card__description">{description}</p>
          )}
        </div>
      </div>

      <span className={`billing-usage-status billing-usage-status--${state}`}>
        {status}
      </span>
    </div>
  );
}

export function UsageLimitGrid({
  usage = {},
  limits = {},
  features = {},
  locale,
  t
}) {
  /*
   * Limits are the entitlement source of truth.
   * A feature may legitimately have no usage row yet.
   */
  const keys = Object.keys(limits || {});

  if (!keys.length) {
    return (
      <p className="billing-usage-unavailable">
        {t("billing.management.usageUnavailable")}
      </p>
    );
  }

  return (
    <div className="billing-usage-grid">
      {keys.map((key) => {
        const rawUsed = usage?.[key];
        const rawLimit = limits?.[key];
        const featureData = features?.[key];

        const label =
          locale === "ar" && featureData?.name_ar
            ? featureData.name_ar
            : featureData?.name || t(`billing.management.usageLabels.${key}`);

        const description =
          locale === "ar" && featureData?.description_ar
            ? featureData.description_ar
            : featureData?.description;

        const unit =
          locale === "ar" && featureData?.unit_ar
            ? featureData.unit_ar
            : featureData?.unit || "";

        const calculationUnit = featureData?.unit || unit;

        const featureType = getFeatureType(featureData, rawUsed, rawLimit);

        /*
         * BOOLEAN FEATURES
         */
        if (featureType === "boolean") {
          // Boolean features are entitlements.
          // If the feature exists in `limits`, it is linked to the
          // current plan and therefore included.
          //
          // An explicit boolean false is still respected if the
          // backend ever supports it.
          const enabled =
            typeof rawLimit === "boolean"
              ? rawLimit
              : Object.prototype.hasOwnProperty.call(limits, key);

          const state = enabled ? "included" : "not-included";
          return (
            <article
              className={`billing-usage-card billing-usage-card--entitlement is-${state}`}
              key={key}
            >
              <UsageCardHeader
                featureKey={key}
                label={label}
                description={description}
                state={state}
                status={
                  enabled
                    ? t("billing.management.included")
                    : t("billing.management.notIncluded")
                }
              />

              <div className="billing-usage-entitlement-panel">
                <span className="billing-usage-entitlement-panel__icon">
                  {enabled ? <Check size={21} /> : <AlertTriangle size={20} />}
                </span>

                <strong>
                  {enabled
                    ? t("billing.management.included")
                    : t("billing.management.notIncluded")}
                </strong>
              </div>
            </article>
          );
        }

        /*
         * UNLIMITED FEATURES
         */
        if (featureType === "unlimited") {
          return (
            <article
              className="billing-usage-card billing-usage-card--entitlement is-unlimited"
              key={key}
            >
              <UsageCardHeader
                featureKey={key}
                label={label}
                description={description}
                state="unlimited"
                status={t("billing.management.unlimited")}
              />

              <div className="billing-usage-entitlement-panel">
                <span className="billing-usage-entitlement-panel__icon">
                  <InfinityIcon size={22} />
                </span>

                <strong>{t("billing.management.unlimited")}</strong>
              </div>
            </article>
          );
        }

        /*
         * INVALID / UNKNOWN FEATURE
         */
        if (featureType === "unknown") {
          return (
            <article className="billing-usage-card is-unavailable" key={key}>
              <UsageCardHeader
                featureKey={key}
                label={label}
                description={description}
                state="unavailable"
                status={t("billing.management.usageUnavailable")}
              />
            </article>
          );
        }

        const numericLimit = toFiniteNumber(rawLimit);
        const parsedUsed = toFiniteNumber(rawUsed);

        const used = parsedUsed === null ? 0 : Math.max(0, parsedUsed);

        if (numericLimit === null || numericLimit < 0) {
          return (
            <article className="billing-usage-card is-unavailable" key={key}>
              <UsageCardHeader
                featureKey={key}
                label={label}
                description={description}
                state="unavailable"
                status={t("billing.management.usageUnavailable")}
              />
            </article>
          );
        }

        /*
         * ZERO ALLOWANCE
         */
        if (numericLimit === 0) {
          return (
            <article
              className="billing-usage-card billing-usage-card--entitlement is-not-included"
              key={key}
            >
              <UsageCardHeader
                featureKey={key}
                label={label}
                description={description}
                state="not-included"
                status={t("billing.management.notIncluded")}
              />

              <div className="billing-usage-entitlement-panel">
                <span className="billing-usage-entitlement-panel__icon">
                  <AlertTriangle size={20} />
                </span>

                <strong>{t("billing.management.notIncluded")}</strong>
              </div>
            </article>
          );
        }

        /*
         * METERED FEATURE
         */
        const limit = numericLimit;

        const percentage = (used / limit) * 100;

        const displayedPercentage = Math.max(0, percentage);

        const progressPercentage = Math.min(100, displayedPercentage);

        const remaining = Math.max(0, limit - used);

        const exceeded = Math.max(0, used - limit);

        const isOverLimit = exceeded > 0;

        const state = getUsageState(used, limit);

        return (
          <article
            className={`billing-usage-card billing-usage-card--metered is-${state}${
              isOverLimit ? " is-over-limit" : ""
            }`}
            key={key}
          >
            <UsageCardHeader
              featureKey={key}
              label={label}
              description={description}
              state={state}
              status={t(`billing.management.usageState.${state}`)}
            />

            <div className="billing-usage-card__metric">
              <div className="billing-usage-card__percentage">
                <strong>
                  {formatNumber(
                    displayedPercentage,
                    locale,
                    displayedPercentage < 1 ? 2 : 1
                  )}
                  %
                </strong>

                <span>{t("billing.management.used")}</span>
              </div>

              <div className="billing-usage-card__remaining-summary">
                <UsageValue
                  value={isOverLimit ? exceeded : remaining}
                  unit={calculationUnit}
                  locale={locale}
                />

                <span>
                  {isOverLimit
                    ? t("billing.management.overLimit")
                    : t("billing.management.remaining")}
                </span>
              </div>
            </div>

            <div
              className="billing-usage-progress"
              role="progressbar"
              aria-label={label}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round(progressPercentage)}
              aria-valuetext={`${formatNumber(
                displayedPercentage,
                locale,
                1
              )}%`}
            >
              <span
                style={{
                  width: `${progressPercentage}%`
                }}
              />
            </div>

            <div className="billing-usage-card__breakdown">
              <div>
                <span>{t("billing.management.used")}</span>

                <UsageValue
                  value={used}
                  unit={calculationUnit}
                  locale={locale}
                />
              </div>

              <div>
                <span>{t("billing.management.limit")}</span>

                <UsageValue
                  value={limit}
                  unit={calculationUnit}
                  locale={locale}
                />
              </div>

              <div>
                <span>
                  {isOverLimit
                    ? t("billing.management.overLimit")
                    : t("billing.management.remaining")}
                </span>

                <UsageValue
                  value={isOverLimit ? exceeded : remaining}
                  unit={calculationUnit}
                  locale={locale}
                />
              </div>
            </div>
          </article>
        );
      })}
    </div>
  );
}
