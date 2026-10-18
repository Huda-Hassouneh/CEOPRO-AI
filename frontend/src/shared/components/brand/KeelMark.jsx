import { useId } from 'react';

// The KEEL symbol: a "K" built from three glass bars - a slanted stem and two
// arms that open to the right, like insight spreading outward. Drawn as
// liquid glass: each bar a translucent gradient with a light rim, a top sheen
// and, at larger sizes, an iridescent edge.
//
// Colours come from the --keel-logo-* tokens (styles/apex-theme.css), so the
// palette is one place to change. "tile" is the app-icon form used on the
// gradient squares in the navigation, sign-in pages and landing page;
// "plain" is for light or dark backgrounds.
export const KEEL_STEM = 'M24 56 Q24 50 29.5 47 L50 36 Q56 33 56 40 L56 164 Q56 171 50 168 L29.5 157 Q24 154 24 148 Z';
export const KEEL_ARM_UPPER = 'M131 32 L170 32 Q177 32 172.5 37.4 L116 98.6 Q113.5 101 110 101 L71 101 Q64 101 68.5 95.6 L125 34.4 Q127.5 32 131 32 Z';
export const KEEL_ARM_LOWER = 'M71 107 L110 107 Q113.5 107 116 109.4 L172.5 170.6 Q177 176 170 176 L131 176 Q127.5 176 125 173.6 L68.5 112.4 Q64 107 71 107 Z';

export default function KeelMark({ size = 22, title, variant = 'tile' }) {
  const id = useId().replace(/:/g, '');
  const token = (part) => `var(--keel-logo-${variant}-${part})`;
  const width = Math.round(size * (168 / 158) * 100) / 100;
  const detailed = size >= 28;
  return (
    <svg className={`keel-mark keel-mark--${variant}`} width={width} height={size} viewBox="16 25 168 158" fill="none"
      role={title ? 'img' : undefined} aria-hidden={title ? undefined : 'true'} aria-label={title}>
      <defs>
        <linearGradient id={`${id}s`} x1="0" y1="0" x2=".35" y2="1"><stop offset="0" stopColor={token('keel-top')} /><stop offset="1" stopColor={token('keel-bottom')} /></linearGradient>
        <linearGradient id={`${id}u`} x1="1" y1="0" x2="0" y2="1"><stop offset="0" stopColor={token('hull-top')} /><stop offset="1" stopColor={token('hull-bottom')} /></linearGradient>
        <linearGradient id={`${id}l`} x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor={token('bulb-light')} /><stop offset="1" stopColor={token('bulb-dark')} /></linearGradient>
        <linearGradient id={`${id}g`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#fff" stopOpacity=".7" /><stop offset=".42" stopColor="#fff" stopOpacity=".1" /><stop offset=".55" stopColor="#fff" stopOpacity="0" /></linearGradient>
        <linearGradient id={`${id}i`} x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#bdf4ff" /><stop offset=".5" stopColor="#ffffff" /><stop offset="1" stopColor="#d8c8ff" /></linearGradient>
      </defs>
      {[[KEEL_STEM, 's'], [KEEL_ARM_UPPER, 'u'], [KEEL_ARM_LOWER, 'l']].map(([d, fill]) => (
        <g key={fill}>
          <path d={d} fill={`url(#${id}${fill})`} fillOpacity=".9" stroke={token('rim')} strokeWidth="2.2" strokeLinejoin="round" />
          <path d={d} fill={`url(#${id}g)`} />
          {detailed ? <path d={d} stroke={`url(#${id}i)`} strokeWidth="1" strokeLinejoin="round" opacity=".55" /> : null}
        </g>
      ))}
    </svg>
  );
}
