import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const api = "http://paper-broker.oppenheimer.studio";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/v1": { target: api, changeOrigin: true },
      "/health": { target: api, changeOrigin: true },
    },
  },
});
