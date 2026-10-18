import process from 'node:process';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Codespaces serves the dev server on https://<codespace>-5173.<domain>;
// Vite refuses Host headers it doesn't know ("Blocked request. This host is
// not allowed"), so the forwarding domain is allowed explicitly.
const codespacesDomain = process.env.GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN || 'app.github.dev';

export default defineConfig({
  plugins: [react()],
  server: {
    allowedHosts: [`.${codespacesDomain}`],
    // VITE_API_BASE_URL=/api (set by .devcontainer/start-services.sh in a
    // Codespace): the browser calls the API on the frontend's own origin and
    // the dev server forwards it to the backend - no cross-origin request,
    // and the backend's port never has to be made public.
    proxy: {
      '/api': {
        target: process.env.KEEL_API_PROXY_TARGET || 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
  build: {
    // The only chunks above Vite's 500 kB default are the 3D runtime's own
    // files (@splinetool/runtime: ~650 kB each), which load only when a 3D
    // scene is set for the landing page (features/landing/SplineHero.jsx).
    // The app's own chunks stay well under this, so a new warning still
    // means something grew.
    chunkSizeWarningLimit: 700,
  },
});
