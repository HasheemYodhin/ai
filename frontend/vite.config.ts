import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const rootDir = fileURLToPath(new URL('.', import.meta.url))

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(rootDir, './src'),
    },
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    // Polling avoids ENOSPC when the system-wide inotify watcher limit is
    // already consumed by editors, containers, or other development servers.
    watch: {
      usePolling: true,
      interval: 300,
    },
    proxy: {
      '/v1': {
        target: process.env.VITE_API_URL || 'http://127.0.0.1:8080',
        changeOrigin: true,
      },
    },
  },
  build: {
    chunkSizeWarningLimit: 1000,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('lucide-react')) return 'lucide'
          if (id.includes('simple-icons')) return 'simple-icons'
          // jspdf/docx/exceljs/pptxgenjs are NOT forced into manual chunks:
          // they are only reached via dynamic import() in lib/download.ts, so
          // Rollup splits them automatically. Forcing them made Rollup place a
          // shared helper in the "pdf" chunk, which the entry then imported,
          // preloading ~390 KB of jsPDF on every first visit.
        },
      },
    },
  },
})
