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
    // Vite 5.4+ blocks requests whose Host header isn't in `allowedHosts`
    // (DNS-rebinding protection). Setting to `true` allows any host —
    // appropriate for a self-hosted LAN dashboard like http://pi5-8.local.
    allowedHosts: true,
    // Listen on all interfaces; equivalent to `--host 0.0.0.0`. Required
    // when running headless on a Pi and reaching the dashboard from another
    // machine on the LAN.
    host: true,
    proxy: {
      // `ws: true` is required for the radiometric WebSocket
      // (/api/radiometric/{camera_id}) to upgrade through the dev proxy.
      // Without it, the WS handshake silently 404s and the FLIR overlay
      // never gets a thermal frame.
      "/api": {
        target: "http://localhost:8001",
        ws: true,
        changeOrigin: true,
        // Forward original Host as X-Forwarded-Host so the backend can use the
        // dashboard's real hostname when constructing WebRTC/HLS/RTSP URLs.
        // Without this, URLs come back with 127.0.0.1 baked in and the browser
        // can't reach MediaMTX when accessing the dashboard from another machine.
        xfwd: true,
      },
    },
  },
});
