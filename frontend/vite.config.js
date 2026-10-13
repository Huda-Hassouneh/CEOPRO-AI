import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  build: {
    // The only chunks above Vite's 500 kB default are the 3D runtime's own
    // files (@splinetool/runtime: ~650 kB each), which load only when a 3D
    // scene is set for the landing page (features/landing/SplineHero.jsx).
    // The app's own chunks stay well under this, so a new warning still
    // means something grew.
    chunkSizeWarningLimit: 700,
  },
});
