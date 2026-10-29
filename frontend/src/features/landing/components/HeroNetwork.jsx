import { useEffect, useRef } from 'react';

// The hero's living backdrop: a constellation of data points that drift,
// link up when close, and carry pulses of light along their links - your
// signals flowing together. The cursor joins the network: nearby points lean
// toward it and link to it. Drawn in the theme's accent colour (re-read when
// the theme changes). It pauses while the hero is off screen or the tab is
// hidden, and is a single still frame under prefers-reduced-motion.
// tone="light" draws it in white, for a coloured band (the final call to action).
const LINK_DISTANCE = 150;
const CURSOR_DISTANCE = 210;

function accentRgb() {
  const probe = document.createElement('span');
  probe.style.color = 'var(--apex-accent, #5b63ec)';
  document.body.appendChild(probe);
  const match = getComputedStyle(probe).color.match(/\d+(\.\d+)?/g) || [91, 99, 236];
  probe.remove();
  return match.slice(0, 3).join(', ');
}

export function HeroNetwork({ tone = 'accent', className = 'lp-hero-network' }) {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const host = canvas?.parentElement;
    const ctx = canvas?.getContext?.('2d');
    if (!canvas || !host || !ctx) return undefined;
    const still = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

    let width = 0, height = 0, nodes = [], pulses = [], frame = 0, visible = true, last = 0;
    const colour = () => (tone === 'light' ? '255, 255, 255' : accentRgb());
    let rgb = colour();
    const cursor = { x: 0, y: 0, active: false };

    const seed = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      width = host.clientWidth; height = host.clientHeight;
      canvas.width = width * dpr; canvas.height = height * dpr;
      canvas.style.width = `${width}px`; canvas.style.height = `${height}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const count = Math.round(Math.min(90, Math.max(28, (width * height) / 14000)));
      nodes = Array.from({ length: count }, () => ({
        x: Math.random() * width, y: Math.random() * height,
        vx: (Math.random() - 0.5) * 0.35, vy: (Math.random() - 0.5) * 0.35,
        r: 1.2 + Math.random() * 1.8, phase: Math.random() * Math.PI * 2,
      }));
      pulses = [];
    };

    const draw = (time) => {
      ctx.clearRect(0, 0, width, height);
      const links = [];
      for (let i = 0; i < nodes.length; i += 1) {
        for (let j = i + 1; j < nodes.length; j += 1) {
          const a = nodes[i], b = nodes[j];
          const d = Math.hypot(a.x - b.x, a.y - b.y);
          if (d < LINK_DISTANCE) {
            links.push([a, b]);
            ctx.strokeStyle = `rgba(${rgb}, ${0.22 * (1 - d / LINK_DISTANCE)})`;
            ctx.lineWidth = 1;
            ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
          }
        }
      }
      if (cursor.active) {
        for (const n of nodes) {
          const d = Math.hypot(n.x - cursor.x, n.y - cursor.y);
          if (d < CURSOR_DISTANCE) {
            ctx.strokeStyle = `rgba(${rgb}, ${0.5 * (1 - d / CURSOR_DISTANCE)})`;
            ctx.lineWidth = 1.2;
            ctx.beginPath(); ctx.moveTo(n.x, n.y); ctx.lineTo(cursor.x, cursor.y); ctx.stroke();
          }
        }
        const glow = ctx.createRadialGradient(cursor.x, cursor.y, 0, cursor.x, cursor.y, 120);
        glow.addColorStop(0, `rgba(${rgb}, 0.16)`); glow.addColorStop(1, `rgba(${rgb}, 0)`);
        ctx.fillStyle = glow; ctx.beginPath(); ctx.arc(cursor.x, cursor.y, 120, 0, Math.PI * 2); ctx.fill();
      }
      for (const n of nodes) {
        const twinkle = 0.55 + 0.45 * Math.sin(time / 900 + n.phase);
        ctx.fillStyle = `rgba(${rgb}, ${0.35 + 0.45 * twinkle})`;
        ctx.beginPath(); ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2); ctx.fill();
      }
      // Pulses: a bright bead with a soft halo running along a link.
      if (!still && links.length && pulses.length < 14 && Math.random() < 0.08) {
        const [a, b] = links[Math.floor(Math.random() * links.length)];
        pulses.push(Math.random() < 0.5 ? { a, b, t: 0 } : { a: b, b: a, t: 0 });
      }
      pulses = pulses.filter((p) => p.t <= 1);
      for (const p of pulses) {
        const x = p.a.x + (p.b.x - p.a.x) * p.t, y = p.a.y + (p.b.y - p.a.y) * p.t;
        const halo = ctx.createRadialGradient(x, y, 0, x, y, 9);
        halo.addColorStop(0, `rgba(${rgb}, 0.9)`); halo.addColorStop(1, `rgba(${rgb}, 0)`);
        ctx.fillStyle = halo; ctx.beginPath(); ctx.arc(x, y, 9, 0, Math.PI * 2); ctx.fill();
        ctx.fillStyle = 'rgba(255, 255, 255, 0.95)';
        ctx.beginPath(); ctx.arc(x, y, 1.6, 0, Math.PI * 2); ctx.fill();
        p.t += 0.018;
      }
    };

    const step = (time) => {
      const dt = Math.min(3, last ? (time - last) / 16.7 : 1);
      last = time;
      for (const n of nodes) {
        if (cursor.active) {
          const dx = cursor.x - n.x, dy = cursor.y - n.y, d = Math.hypot(dx, dy);
          if (d < CURSOR_DISTANCE && d > 1) { n.vx += (dx / d) * 0.012 * dt; n.vy += (dy / d) * 0.012 * dt; }
        }
        n.vx *= 0.992; n.vy *= 0.992;
        const speed = Math.hypot(n.vx, n.vy);
        if (speed < 0.12) { n.vx += (Math.random() - 0.5) * 0.02; n.vy += (Math.random() - 0.5) * 0.02; }
        if (speed > 1.2) { n.vx *= 1.2 / speed; n.vy *= 1.2 / speed; }
        n.x += n.vx * dt; n.y += n.vy * dt;
        if (n.x < -20) n.x = width + 20; else if (n.x > width + 20) n.x = -20;
        if (n.y < -20) n.y = height + 20; else if (n.y > height + 20) n.y = -20;
      }
      draw(time);
      frame = requestAnimationFrame(step);
    };

    const start = () => { if (!still && !frame && visible && !document.hidden) { last = 0; frame = requestAnimationFrame(step); } };
    const stop = () => { cancelAnimationFrame(frame); frame = 0; };

    seed();
    draw(0);
    if (still) return undefined;

    const onMove = (event) => {
      const box = host.getBoundingClientRect();
      cursor.x = event.clientX - box.left; cursor.y = event.clientY - box.top; cursor.active = true;
    };
    const onLeave = () => { cursor.active = false; };
    const onVisibility = () => (document.hidden ? stop() : start());
    const resize = new ResizeObserver(() => { seed(); if (!frame) draw(0); });
    const seen = new IntersectionObserver(([entry]) => { visible = entry.isIntersecting; if (visible) start(); else stop(); });
    const theme = new MutationObserver(() => { rgb = colour(); });

    host.addEventListener('pointermove', onMove);
    host.addEventListener('pointerleave', onLeave);
    document.addEventListener('visibilitychange', onVisibility);
    resize.observe(host);
    seen.observe(host);
    theme.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme', 'class'] });
    start();
    return () => {
      stop();
      host.removeEventListener('pointermove', onMove);
      host.removeEventListener('pointerleave', onLeave);
      document.removeEventListener('visibilitychange', onVisibility);
      resize.disconnect(); seen.disconnect(); theme.disconnect();
    };
  }, [tone]);

  return <canvas ref={canvasRef} className={className} aria-hidden="true" />;
}

export default HeroNetwork;
