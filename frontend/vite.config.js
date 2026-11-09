import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// A same-origin gateway for the browser. The separate FastAPI services still
// run independently on their agreed ports; Vite only proxies requests in dev.
export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 3000,
    strictPort: true,
    proxy: {
      '/gateway/availability': {
        target: 'http://127.0.0.1:5002',
        changeOrigin: true,
        rewrite: path => path.replace(/^\/gateway\/availability/, ''),
      },
      '/gateway/booking': {
        target: 'http://127.0.0.1:5001',
        changeOrigin: true,
        rewrite: path => path.replace(/^\/gateway\/booking/, ''),
      },
      '/gateway/notifications': {
        target: 'http://127.0.0.1:5003',
        changeOrigin: true,
        rewrite: path => path.replace(/^\/gateway\/notifications/, ''),
      },
    },
  },
});
