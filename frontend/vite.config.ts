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
          if (id.includes('/docx/')) return 'word'
          if (id.includes('/jspdf/')) return 'pdf'
          if (id.includes('/exceljs/')) return 'excel'
          if (id.includes('/pptxgenjs/')) return 'powerpoint'
        },
      },
    },
  },
})
