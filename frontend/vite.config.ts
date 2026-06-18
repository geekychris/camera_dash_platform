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
      "/api": "http://localhost:8001",
    },
  },
});
