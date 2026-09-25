import { useId, useState } from "react";

const snapToStep = (value, min, max, step) => {
  const clamped = Math.min(max, Math.max(min, value));
  if (!step || step <= 1) return Math.round(clamped);
  const snapped = min + Math.round((clamped - min) / step) * step;
  return Math.min(max, Math.max(min, snapped));
};

export function CustomPlanQuantityField({
  label,
  value,
  min,
  max,
  step = 1,
  onChange,
  formatValue
}) {
  const id = useId();
  const [draft, setDraft] = useState(null);

  const commit = () => {
    if (draft !== null && draft !== "") {
      onChange(snapToStep(Number(draft), min, max, step));
    }
    setDraft(null);
  };

  return (
    <section className="ceopro-custom-quantity">
      <input
        id={id}
        type="text"
        inputMode="numeric"
        pattern="[0-9]*"
        dir="ltr"
        aria-label={label}
        aria-describedby={`${id}-bounds`}
        value={draft ?? String(value)}
        aria-invalid={
          draft !== null &&
          draft !== "" &&
          (Number(draft) < min || Number(draft) > max)
        }
        onChange={(event) => {
          const next = event.target.value.replace(/[٠-٩۰-۹]/g, (digit) =>
            String(digit.charCodeAt(0) - (digit <= "٩" ? 1632 : 1776))
          );

          if (!/^\d*$/.test(next)) return;
          setDraft(next);

          if (next !== "" && Number(next) >= min && Number(next) <= max) {
            const numeric = Number(next);
            if ((numeric - min) % step === 0) onChange(numeric);
          }
        }}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            commit();
          }
          if (event.key === "Escape") setDraft(null);
        }}
      />

      <div id={`${id}-bounds`} className="ceopro-range-field__bounds">
        <span>
          {formatValue(min)} – {formatValue(max)}
        </span>
      </div>
    </section>
  );
}
