import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  // Tailwind v4 compiles the utility classes used across App.tsx, components/
  // and onboarding/ from src/index.css. Without this plugin the dashboard
  // shipped completely unstyled.
  plugins: [react(), tailwindcss()],
  root: '.',
  server: {
    // README documents http://localhost:3000.
    port: 3000,
  },
  build: {
    outDir: 'dist',
  },
});
