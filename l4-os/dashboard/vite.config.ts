import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/status.json": {
        target: "http://127.0.0.1:8767",
        changeOrigin: false,
      },
      "/ssh-hosts": {
        target: "http://127.0.0.1:8767",
        changeOrigin: false,
      },
      "/api/chat": {
        target: "http://127.0.0.1:8767",
        changeOrigin: false,
      },
      "/api/actions": {
        target: "http://127.0.0.1:8767",
        changeOrigin: false,
      },
      "/wfctl": {
        target: "http://127.0.0.1:8799",
        changeOrigin: false,
      },
      "/graph-data": {
        target: "http://127.0.0.1:8799",
        changeOrigin: false,
      },
    },
  },
  preview: {
    host: "127.0.0.1",
    port: 4173,
  },
});
