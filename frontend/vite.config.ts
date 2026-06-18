import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // react-rnd / react-draggable reference `process.env.NODE_ENV` in dev paths;
  // Vite doesn't expose `process` in the browser by default. Shim it so those
  // lookups don't throw.
  define: {
    "process.env.NODE_ENV": JSON.stringify("development"),
    "process.env": "{}",
  },
  server: {
    port: 5173,
    proxy: {
      // `ws: true` is required for the radiometric WebSocket
      // (/api/radiometric/{camera_id}) to upgrade through the dev proxy.
      // Without it, the WS handshake silently 404s and the FLIR overlay
      // never gets a thermal frame.
      "/api": { target: "http://localhost:8001", ws: true, changeOrigin: true },
    },
  },
});
