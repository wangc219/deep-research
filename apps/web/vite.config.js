import {defineConfig, loadEnv} from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({mode}) => {
  const env = loadEnv(mode, '../../', '');
  const host = process.env.EQUIPMENT_DR_WEB_HOST
    || env.EQUIPMENT_DR_WEB_HOST
    || '0.0.0.0';
  const port = Number(
    process.env.EQUIPMENT_DR_WEB_PORT
      || env.EQUIPMENT_DR_WEB_PORT
      || 5173,
  );
  const allowedHosts = (
    process.env.EQUIPMENT_DR_WEB_ALLOWED_HOSTS
      || env.EQUIPMENT_DR_WEB_ALLOWED_HOSTS
      || '12738agqw5541.vicp.fun'
  )
    .split(',')
    .map((value) => value.trim())
    .filter(Boolean);
  return {
    // Keep emitted assets relative so the workbench can be served from a subdirectory.
    base: './',
    plugins: [react()],
    resolve: {
      alias: {
        buffer: 'buffer',
      },
    },
    envDir: '../../',
    server: {
      host,
      port,
      strictPort: true,
      allowedHosts,
      proxy: {
        '/api': process.env.VITE_API_PROXY_TARGET
          || env.VITE_API_PROXY_TARGET
          || 'http://127.0.0.1:8000',
      },
    },
    preview: {
      host,
      port,
      strictPort: true,
      allowedHosts,
    },
  };
});
