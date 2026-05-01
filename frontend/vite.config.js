import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: path.resolve(__dirname, "../app/static/dist"),
    emptyOutDir: true,
  },
  server: {
    host: "0.0.0.0",
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/v1": "http://127.0.0.1:8000",
      "/static": "http://127.0.0.1:8000",
      "/health": "http://127.0.0.1:8000",
    },
  },
});
