import base44 from "@base44/vite-plugin"
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import path from 'path'
import { visualizer } from 'rollup-plugin-visualizer'
import { nodePolyfills } from 'vite-plugin-node-polyfills'

// https://vite.dev/config/
export default defineConfig({
  define: {
    'global': 'window',
    'node:fs': false,
    'node:net': false,
    'fetch-blob': false,
  },
  logLevel: 'info', // Show server URL and info
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
      'stream-browserify/web': path.resolve(__dirname, 'src/shims/stream-web.cjs'),
      'node:stream/web': path.resolve(__dirname, 'src/shims/stream-web.cjs'),
    },
  },
  plugins: [
    nodePolyfills({
      globals: {
        Buffer: true,
        global: true,
        process: true,
      },
      // Allow all polyfills to ensure @solana/web3.js works
      protocolImports: true,
    }),
    base44({
      // Support for legacy code that imports the base44 SDK with @/integrations, @/entities, etc.
      // can be removed if the code has been updated to use the new SDK imports from @base44/sdk
      legacySDKImports: process.env.BASE44_LEGACY_SDK_IMPORTS === 'true',
      hmrNotifier: true,
      navigationNotifier: true,
      visualEditAgent: true
    }),
    react({
      // Use automatic JSX runtime
      jsxRuntime: 'automatic',
      // Fast refresh for better DX
      fastRefresh: true,
    }),
    // Bundle analyzer - generates stats.html in build
    visualizer({
      open: false,
      gzipSize: true,
      brotliSize: true,
      filename: 'dist/stats.html'
    }),
  ],
  optimizeDeps: {
    // Include React for proper ESM module resolution in preview/sandbox environments
    include: ['react', 'react-dom', 'react/jsx-runtime', 'react/jsx-dev-runtime', '@solana/web3.js', '@solana/spl-token'],
    // Exclude the WASM glue so Vite doesn't try to prebundle it
    exclude: ['@/quantum-core/pkg/quantum_core']
  },
  assetsInclude: ['**/*.wasm'],
  build: {
    // Target modern browsers for smaller bundle
    target: 'es2020',

    // Minification with terser
    minify: 'terser',
    terserOptions: {
      compress: {
        drop_console: true,
        drop_debugger: true,
        pure_funcs: ['console.log', 'console.info', 'console.debug']
      },
      format: {
        comments: false
      }
    },

    // Standard chunk size warning limit (do not hide the problem)
    chunkSizeWarningLimit: 500,

    // CSS code splitting
    cssCodeSplit: true,

    // Source maps (disable in production)
    sourcemap: false,

    rollupOptions: {
      output: {
        // Manual chunk splitting for better caching
        manualChunks: {
          'vendor-react': ['react', 'react-dom', 'react-router-dom'],
          'vendor-query': ['@tanstack/react-query'],
          'vendor-ui': [
            '@radix-ui/react-dialog',
            '@radix-ui/react-dropdown-menu',
            '@radix-ui/react-tabs',
            '@radix-ui/react-select',
            '@radix-ui/react-popover',
            '@radix-ui/react-accordion',
            '@radix-ui/react-tooltip'
          ],
          'vendor-charts': ['recharts'],
          'vendor-motion': ['framer-motion'],
          'vendor-editor': ['react-quill', 'quill'],
          'vendor-icons': ['lucide-react'],
          'vendor-three': ['three', '@react-three/fiber', '@react-three/drei'],
          'vendor-solana': ['@solana/web3.js', '@solana/spl-token'],
          'vendor-utils': ['clsx', 'tailwind-merge', 'class-variance-authority', 'date-fns', 'zod', 'axios'],
        },
      },
    },
  },});
