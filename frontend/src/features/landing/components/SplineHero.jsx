import { useEffect, useRef, useState } from 'react';

// An optional 3D hero scene made in Spline. It only loads when a scene URL is
// configured (VITE_SPLINE_HERO_SCENE), the visitor hasn't asked for reduced
// motion, and the browser supports WebGL; the runtime is fetched on demand.
// Until the scene is ready - or if it can't load - the static visual shows.
const SCENE = import.meta.env.VITE_SPLINE_HERO_SCENE;

function canRender3d() {
  if (!SCENE || typeof window === 'undefined') return false;
  if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return false;
  if (navigator.connection?.saveData) return false;
  try {
    const canvas = document.createElement('canvas');
    return Boolean(canvas.getContext('webgl2') || canvas.getContext('webgl'));
  } catch {
    return false;
  }
}

export function SplineHero({ fallback, label }) {
  const canvasRef = useRef(null);
  const [state, setState] = useState(() => (canRender3d() ? 'loading' : 'off'));

  useEffect(() => {
    if (state !== 'loading') return undefined;
    let app = null;
    let cancelled = false;
    import('@splinetool/runtime')
      .then(({ Application }) => {
        if (cancelled || !canvasRef.current) return null;
        app = new Application(canvasRef.current);
        return app.load(SCENE);
      })
      .then(() => { if (!cancelled && app) setState('ready'); })
      .catch(() => { if (!cancelled) setState('off'); });
    return () => {
      cancelled = true;
      app?.dispose?.();
    };
  }, [state]);

  if (state === 'off') return fallback;
  return (
    <div className={`lp-spline${state === 'ready' ? ' is-ready' : ''}`}>
      {state !== 'ready' && <div className="lp-spline__fallback">{fallback}</div>}
      <canvas ref={canvasRef} className="lp-spline__canvas" role="img" aria-label={label} />
    </div>
  );
}

export default SplineHero;
