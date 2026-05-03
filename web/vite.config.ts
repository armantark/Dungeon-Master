import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";

// Vite proxies /api -> the FastAPI server on :8000 so the frontend can use
// same-origin URLs in both dev and (eventual) production-bundled mode.
export default defineConfig({
  plugins: [svelte()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: false,
      },
    },
  },
  build: {
    target: "es2022",
    sourcemap: true,
  },
});
