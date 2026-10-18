import {
  ArrowDown,
  ArrowUp,
  Eye,
  Minus,
  PackagePlus,
  PackageX
} from "lucide-react";

const icons = {
  increasing: ArrowUp,
  decreasing: ArrowDown,
  stable: Minus,
  restock: PackagePlus,
  reduce: PackageX,
  monitor: Eye
};

export function DemandStatusBadge({ value, namespace, t }) {
  if (!icons[value]) {
    return <span>{t("demandApproved.common.notAvailable")}</span>;
  }

  const Icon = icons[value];
  return (
    <span className={`demand-approved-badge is-${value}`}>
      <Icon size={12} aria-hidden="true" />
      {t(`${namespace}.${value}`)}
    </span>
  );
}
