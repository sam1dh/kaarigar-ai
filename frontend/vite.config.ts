import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";
import { VitePWA } from "vite-plugin-pwa";

// Live reload through the https tunnel needs the HMR socket on 443/wss,
// which would break plain http://localhost:5173. Only do it when asked.
const tunnelDev = process.env.TUNNEL_DEV === "1";

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
      // No service worker in dev — otherwise the phone caches old code.
      devOptions: {
        enabled: false,
      },
      manifest: {
        name: "Kaarigar",
        short_name: "Kaarigar",
        theme_color: "#1F4239",
        background_color: "#E9EDE8",
        display: "standalone",
        id: "/tech",
        start_url: "/tech",
        scope: "/", // must include /m/… so sticker links belong to the app
        launch_handler: { client_mode: ["navigate-existing", "auto"] }, // reuse the open Kaarigar window
        handle_links: "preferred",
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
      } as any, // older vite-plugin-pwa types don't know launch_handler / handle_links
      workbox: {
        navigateFallback: "/index.html", // /m/<token> always loads the app
        navigateFallbackDenylist: [/^\/api\//],
      },
    }),
  ],
  server: {
    host: "0.0.0.0",
    port: 5173,
    strictPort: true,
    allowedHosts: [
      ".trycloudflare.com",
      "app.kaarigar-ai.online",
      "dev.kaarigar-ai.online",
    ],
    ...(tunnelDev ? { hmr: { clientPort: 443, protocol: "wss" as const } } : {}),
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
  preview: {
    host: true,
    port: 4173,
    allowedHosts: [
      ".trycloudflare.com",
      "app.kaarigar-ai.online",
      "dev.kaarigar-ai.online",
    ],
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
