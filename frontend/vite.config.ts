import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  plugins: [
    react(),
    VitePWA({
      registerType: "autoUpdate",
      includeAssets: ["favicon.svg"],
      // Serve the manifest + service worker in dev too, so the install
      // button works while testing on localhost / the Cloudflare tunnel.
      devOptions: {
        enabled: true,
        type: "module",
      },
      manifest: {
        name: "Kaarigar",
        short_name: "Kaarigar",
        theme_color: "#1F4239",
        background_color: "#E9EDE8",
        display: "standalone",
        start_url: "/tech",
        icons: [
          { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png" },
          { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png" },
          {
            src: "/icons/icon-512.png",
            sizes: "512x512",
            type: "image/png",
            purpose: "any maskable",
          },
        ],
      },
    }),
  ],
  server: {
    host: true,
    allowedHosts: [".trycloudflare.com"],
    fs: {
      // allow importing ../shared/languages.json from outside frontend/
      allow: [".."],
    },
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
