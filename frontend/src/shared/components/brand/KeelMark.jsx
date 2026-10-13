import { useId } from 'react';

// The approved KEEL symbol: the bottom of a ship seen head-on - the hull,
// the keel fin below it and the ballast bulb at its tip, the part that keeps
// the boat steady. Drawn as glass: each part a translucent gradient with a
// light rim, a top sheen and an edge highlight.
//
// Colours come from the --keel-logo-* tokens (styles/apex-theme.css), so the
// palette is one place to change. "tile" is the app-icon form used on the
// gradient squares in the navigation, sign-in pages and landing page;
// "plain" is for light or dark backgrounds.
export const KEEL_HULL = 'M18 60 L182 60 C180.5 76 173 87 158 92 L106 101 L94 101 L42 92 C27 87 19.5 76 18 60 Z';
export const KEEL_FIN = 'M86 99 Q92.4 101.4 93 108 L94.8 172 L105.2 172 L107 108 Q107.6 101.4 114 99 Z';

export default function KeelMark({ size = 22, title, variant = 'tile' }) {
  const id = useId().replace(/:/g, '');
  const token = (part) => `var(--keel-logo-${variant}-${part})`;
  const width = Math.round(size * (180 / 148) * 100) / 100;
  return (
    <svg className={`keel-mark keel-mark--${variant}`} width={width} height={size} viewBox="10 46 180 148" fill="none"
      role={title ? 'img' : undefined} aria-hidden={title ? undefined : 'true'} aria-label={title}>
      <defs>
        <linearGradient id={`${id}h`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor={token('hull-top')} /><stop offset="1" stopColor={token('hull-bottom')} /></linearGradient>
        <linearGradient id={`${id}k`} x1="0" y1="0" x2=".4" y2="1"><stop offset="0" stopColor={token('keel-top')} /><stop offset="1" stopColor={token('keel-bottom')} /></linearGradient>
        <radialGradient id={`${id}b`} cx="38%" cy="30%" r="75%"><stop offset="0" stopColor="#fff" stopOpacity=".9" /><stop offset=".35" stopColor={token('bulb-light')} /><stop offset="1" stopColor={token('bulb-dark')} /></radialGradient>
        <linearGradient id={`${id}s`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#fff" stopOpacity=".75" /><stop offset=".45" stopColor="#fff" stopOpacity=".08" /><stop offset=".55" stopColor="#fff" stopOpacity="0" /></linearGradient>
      </defs>
      <path d={KEEL_HULL} fill={`url(#${id}h)`} fillOpacity=".92" stroke={token('rim')} strokeWidth="2.4" strokeLinejoin="round" />
      <path d={KEEL_HULL} fill={`url(#${id}s)`} />
      <path d={KEEL_FIN} fill={`url(#${id}k)`} fillOpacity=".96" stroke={token('rim')} strokeWidth="2" strokeLinejoin="round" />
      <circle cx="100" cy="178" r="12" fill={`url(#${id}b)`} stroke={token('rim')} strokeWidth="1.8" />
      {size >= 40 ? (
        <>
          <path d="M22 61.8 L178 61.8" stroke="#fff" strokeWidth="1.6" strokeLinecap="round" opacity=".9" />
          <path d="M96.4 111 L97.6 166" stroke="#fff" strokeWidth="1.3" strokeLinecap="round" opacity=".7" />
        </>
      ) : null}
    </svg>
  );
}
