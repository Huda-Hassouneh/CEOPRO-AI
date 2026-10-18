import { useId } from 'react';

// The KEEL symbol: a "K" whose arms are ribbons - a slanted stem, an upper arm
// rising to the right, and a lower arm that folds out of the stem with a soft
// highlight on the turn. Stem in periwinkle-to-violet, arms in blue easing to
// aqua at the tips.
//
// Colours come from the --keel-logo-* tokens (styles/apex-theme.css), with
// light and dark values, so the palette is one place to change. "tile" is the
// app-icon form on the brand squares (navigation, sign-in, landing); "plain"
// is for open backgrounds.
export const KEEL_STEM = 'M16 58 Q13 60 13 64 L13 256 Q13 261 17 264 L96 318 Q103 322 103 314 L103 16 Q103 8 96 12 Z';
export const KEEL_ARM_UPPER = 'M122 104 L236 33 Q250 24 264 29 L302 44 Q313 50 302 56 L130 148 Q122 152 122 144 Z';
export const KEEL_ARM_LOWER = 'M110 172 Q128 166 146 177 L302 265 Q313 271 302 277 L262 300 Q251 306 240 300 L105 222 Q103 220 103 216 L103 178 Q103 174 110 172 Z';
export const KEEL_FOLD = 'M13 236 Q48 180 122 175 Q132 175 140 179 L136 197 Q76 199 13 272 Z';

export default function KeelMark({ size = 22, title, variant = 'tile' }) {
  const id = useId().replace(/:/g, '');
  const token = (part) => `var(--keel-logo-${variant}-${part})`;
  const width = Math.round(size * (310 / 320) * 100) / 100;
  return (
    <svg className={`keel-mark keel-mark--${variant}`} width={width} height={size} viewBox="8 5 310 320" fill="none"
      role={title ? 'img' : undefined} aria-hidden={title ? undefined : 'true'} aria-label={title}>
      <defs>
        <linearGradient id={`${id}s`} x1="0" y1="0" x2=".25" y2="1">
          <stop offset="0" stopColor={token('stem-top')} />
          <stop offset="1" stopColor={token('stem-bottom')} />
        </linearGradient>
        <linearGradient id={`${id}a`} gradientUnits="userSpaceOnUse" x1="110" y1="0" x2="312" y2="0">
          <stop offset="0" stopColor={token('arm')} />
          <stop offset=".55" stopColor={token('arm')} />
          <stop offset="1" stopColor={token('tip')} />
        </linearGradient>
        <linearGradient id={`${id}f`} gradientUnits="userSpaceOnUse" x1="15" y1="250" x2="150" y2="172">
          <stop offset="0" stopColor={token('tip')} stopOpacity=".05" />
          <stop offset=".5" stopColor={token('tip')} stopOpacity=".6" />
          <stop offset="1" stopColor={token('fold')} stopOpacity=".95" />
        </linearGradient>
      </defs>
      <path d={KEEL_STEM} fill={`url(#${id}s)`} />
      <path d={KEEL_ARM_UPPER} fill={`url(#${id}a)`} />
      <path d={KEEL_ARM_LOWER} fill={`url(#${id}a)`} />
      <path d={KEEL_FOLD} fill={`url(#${id}f)`} />
    </svg>
  );
}
