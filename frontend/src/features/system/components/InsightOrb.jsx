import { memo } from 'react';
import KeelMark from '../../../shared/components/brand/KeelMark.jsx';

// The welcome screen's centrepiece: a liquid-glass orb with luminous data
// particles travelling along curved orbits, market-signal waves and a small
// constellation of connected points. Purely decorative (aria-hidden): the
// meaning is carried by the headline and the insight cards beside it.
//
// The particles move with SVG <animateMotion> so they follow the orbits at
// any size; with reduced motion they are not rendered at all, and every CSS
// animation in WelcomePage.css stops.
const ORBITS = [
  { id: 'kw-orbit-a', d: 'M 70 300 A 230 92 -18 1 1 530 300 A 230 92 -18 1 1 70 300', dur: 14, dots: [0, 0.5] },
  { id: 'kw-orbit-b', d: 'M 120 330 A 190 128 24 1 1 480 270 A 190 128 24 1 1 120 330', dur: 19, dots: [0.2, 0.7] },
  { id: 'kw-orbit-c', d: 'M 160 300 A 140 210 8 1 1 440 300 A 140 210 8 1 1 160 300', dur: 24, dots: [0.4] },
];

const NODES = [[132, 168], [196, 118], [438, 132], [486, 214], [104, 410], [470, 436], [392, 506]];
const LINKS = [[0, 1], [2, 3], [4, 0], [5, 6], [3, 5]];

export const InsightOrb = memo(function InsightOrb({ animate }) {
  return (
    <div className="kw-orb-scene" aria-hidden="true">
      <div className="kw-orb-halo" />
      <svg className="kw-orb-svg" viewBox="0 0 600 600" focusable="false">
        <defs>
          <linearGradient id="kw-orbit-stroke" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#8fb4ff" stopOpacity="0" />
            <stop offset=".45" stopColor="#a99bff" stopOpacity=".55" />
            <stop offset="1" stopColor="#6ee7f9" stopOpacity="0" />
          </linearGradient>
          <linearGradient id="kw-wave-stroke" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0" stopColor="#6ee7f9" stopOpacity="0" />
            <stop offset=".5" stopColor="#7dd3fc" stopOpacity=".7" />
            <stop offset="1" stopColor="#a78bfa" stopOpacity="0" />
          </linearGradient>
          <radialGradient id="kw-particle" cx="50%" cy="50%" r="50%">
            <stop offset="0" stopColor="#ffffff" />
            <stop offset=".35" stopColor="#bfe9ff" />
            <stop offset="1" stopColor="#7dd3fc" stopOpacity="0" />
          </radialGradient>
        </defs>

        <g className="kw-orb-network">
          {LINKS.map(([a, b]) => (
            <line key={`${a}-${b}`} x1={NODES[a][0]} y1={NODES[a][1]} x2={NODES[b][0]} y2={NODES[b][1]} />
          ))}
          {NODES.map(([x, y], index) => (
            <circle key={`${x}-${y}`} cx={x} cy={y} r="2.6" style={{ animationDelay: `${index * 0.7}s` }} />
          ))}
        </g>

        <g className="kw-orb-waves">
          <path d="M 40 470 C 130 430 190 512 280 470 S 430 420 560 462" />
          <path d="M 40 492 C 140 462 210 530 300 492 S 450 450 560 486" />
        </g>

        <g className="kw-orb-orbits">
          {ORBITS.map((orbit) => <path key={orbit.id} id={orbit.id} d={orbit.d} />)}
        </g>

        {animate && ORBITS.flatMap((orbit) => orbit.dots.map((offset) => (
          <g key={`${orbit.id}-${offset}`} className="kw-orb-particle">
            <circle r="9" fill="url(#kw-particle)" opacity=".55" />
            <circle r="2.4" fill="#ffffff" />
            <animateMotion dur={`${orbit.dur}s`} repeatCount="indefinite" begin={`-${orbit.dur * offset}s`}
              keyPoints="0;1" keyTimes="0;1" calcMode="linear">
              <mpath href={`#${orbit.id}`} />
            </animateMotion>
          </g>
        )))}
      </svg>

      <div className="kw-orb">
        <div className="kw-orb-caustics" />
        <div className="kw-orb-core"><KeelMark size={58} variant="plain" /></div>
        <div className="kw-orb-sheen" />
        <div className="kw-orb-rim" />
      </div>

      <div className="kw-shard kw-shard--1" />
      <div className="kw-shard kw-shard--2" />
      <div className="kw-shard kw-shard--3" />
    </div>
  );
});
