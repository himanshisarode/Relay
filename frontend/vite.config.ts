import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    // Docker on Windows doesn't forward file-change events from the host, so poll there.
    watch: process.env.VITE_POLL ? { usePolling: true, interval: 300 } : undefined,
    proxy: {
      "/api": { target: process.env.VITE_API_PROXY ?? "http://localhost:8000", changeOrigin: false },
      "/health": { target: process.env.VITE_API_PROXY ?? "http://localhost:8000" },
    },
  },
  build: {
    rollupOptions: {
      output: { manualChunks: { calendar: ["@fullcalendar/core", "@fullcalendar/react", "@fullcalendar/timegrid", "@fullcalendar/interaction", "@fullcalendar/luxon3", "luxon"] } },
    },
  },
  test: { environment: "jsdom" },
} as never);
