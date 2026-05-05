import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'node:path';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: true,
    chunkSizeWarningLimit: 600,
    rollupOptions: {
      output: {
        // Manual chunks pull common vendor code out of the entry bundle.
        // Each route page is already lazy-loaded; this trims the initial.
        manualChunks: (id) => {
          if (!id.includes('node_modules')) return undefined;
          if (id.includes('@tanstack')) return 'vendor-query';
          if (id.includes('react-router')) return 'vendor-router';
          if (id.includes('react-markdown') || id.includes('remark-')) {
            return 'vendor-markdown';
          }
          if (id.includes('@radix-ui')) return 'vendor-radix';
          if (id.includes('lucide-react')) return 'vendor-icons';
          if (id.includes('cmdk')) return 'vendor-cmdk';
          // React itself stays in the main bundle (small + always-needed)
          return undefined;
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      // Proxy API calls to FastAPI during dev
      '/api': 'http://localhost:8080',
      '/auth': 'http://localhost:8080',
    },
  },
});
