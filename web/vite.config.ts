import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";

// Vite proxies /api -> the FastAPI server on :8000 so the frontend can use
// same-origin URLs in both dev and (eventual) production-bundled mode.
//
// Dev-only escape hatch: `VITE_API_PROXY_TARGET` lets a fixture backend run on
// a different port/root without editing checked-in config. This keeps manual
// browser smoke against canned saves isolated from whatever real campaign is
// bound to :8000.
const apiProxyTarget = process.env.VITE_API_PROXY_TARGET ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [svelte()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: apiProxyTarget,
        changeOrigin: false,
      },
    },
  },
  build: {
    target: "es2022",
    sourcemap: true,
  },
});
