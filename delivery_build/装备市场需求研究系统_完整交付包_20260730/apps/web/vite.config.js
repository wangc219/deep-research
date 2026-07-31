import {defineConfig, loadEnv} from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({mode}) => {
  const env = loadEnv(mode, '../../', '');
  return {
    plugins: [react()],
    envDir: '../../',
    server: {
      port: 5173,
      proxy: {
        '/api': process.env.VITE_API_PROXY_TARGET
          || env.VITE_API_PROXY_TARGET
          || 'http://127.0.0.1:8000',
      },
    },
  };
});
