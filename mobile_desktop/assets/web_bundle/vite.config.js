import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: 'dist',
    rollupOptions: {
      input: {
        canvas: './canvas.html',
        doc: './doc.html',
      },
    },
  },
  base: './',
})
