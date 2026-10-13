import { useEffect, useRef, useState } from 'react';

// Counts the first number inside a formatted value ("JOD 1,234.50",
// "87%", "12") up from its previous value, keeping the surrounding text and
// the original grouping/decimals. Anything without plain digits (or with
// reduced motion) renders as-is.
const NUMBER = /-?\d[\d,]*(?:\.\d+)?/;
const DURATION = 950;

const reducedMotion = () => typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

function split(value) {
  if (typeof value !== 'string' && typeof value !== 'number') return null;
  const text = String(value);
  const match = text.match(NUMBER);
  if (!match) return null;
  const raw = match[0];
  const target = Number(raw.replace(/,/g, ''));
  if (!Number.isFinite(target)) return null;
  const decimals = raw.includes('.') ? raw.split('.')[1].length : 0;
  return { before: text.slice(0, match.index), after: text.slice(match.index + raw.length), target, decimals, grouped: raw.includes(',') };
}

const format = (n, { decimals, grouped }) => {
  const fixed = n.toFixed(decimals);
  if (!grouped) return fixed;
  const [int, frac] = fixed.split('.');
  return int.replace(/\B(?=(\d{3})+(?!\d))/g, ',') + (frac ? `.${frac}` : '');
};

export default function CountUp({ value }) {
  const parts = split(value);
  const [shown, setShown] = useState(() => (parts && !reducedMotion() ? 0 : parts?.target));
  const fromRef = useRef(0);

  useEffect(() => {
    if (!parts || reducedMotion()) { setShown(parts?.target); return undefined; }
    const from = fromRef.current;
    const to = parts.target;
    if (from === to) { setShown(to); return undefined; }
    let frame;
    const start = performance.now();
    const tick = (now) => {
      const p = Math.min(1, (now - start) / DURATION);
      const eased = 1 - (1 - p) ** 3;
      setShown(from + (to - from) * eased);
      if (p < 1) frame = requestAnimationFrame(tick);
      else fromRef.current = to;
    };
    frame = requestAnimationFrame(tick);
    return () => { cancelAnimationFrame(frame); fromRef.current = to; };
  }, [parts?.target]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!parts) return value ?? null;
  // Screen readers get the final value, not every frame.
  return (
    <>
      <span aria-hidden="true">{parts.before}{format(shown ?? parts.target, parts)}{parts.after}</span>
      <span className="sr-only">{String(value)}</span>
    </>
  );
}
