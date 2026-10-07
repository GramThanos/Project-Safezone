// The frontend's build (Vite).
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Where `npm run dev` sends /api and /health. The default is the backend's
// name on the compose network; set API_PROXY_TARGET (for example
// http://localhost:5000) to run the dev server outside it.
const apiTarget = process.env.API_PROXY_TARGET || 'http://backend:5000';

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: 'build',
    // Hashed bundles go under /static/, which nginx caches for a year
    // (nginx.conf). /assets/ is public/assets, whose names never change and
    // which nginx has browsers re-check instead.
    assetsDir: 'static',
  },
  server: {
    port: 3000,
    // Same-origin in development too, as production is behind nginx.
    proxy: {
      '/api': apiTarget,
      '/health': apiTarget,
    },
  },
});
