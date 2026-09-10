import path from "node:path"

import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig, loadEnv } from "vite"
import { mockDashboard } from "./dev/mock-dashboard"

export default defineConfig(({ mode, command }) => {
  const env = loadEnv(mode, path.resolve(__dirname, "../.."), "TUSKOMETR_")
  const dataOrigin = process.env.TUSKOMETR_DATA_ORIGIN || env.TUSKOMETR_DATA_ORIGIN
  const siteOrigin = new URL(process.env.TUSKOMETR_SITE_ORIGIN || env.TUSKOMETR_SITE_ORIGIN || "https://tuskometr.pages.dev").origin
  const useMocks = command === "serve" && !dataOrigin
  return {
    plugins: [react(), tailwindcss(),
      {
        name: "share-metadata",
        transformIndexHtml: (html: string) => html.replaceAll("__TUSKOMETR_SITE_ORIGIN__", siteOrigin),
      },
      ...(useMocks ? [mockDashboard(path.resolve(__dirname, "dev/dashboard.json"))] : []),
    ],
    define: { "import.meta.env.VITE_MOCK_DATA": JSON.stringify(useMocks ? "true" : "false") },
    resolve: {
      alias: {
        "@": path.resolve(__dirname, "./src"),
      },
    },
    server: {
      allowedHosts: ["sati"],
      host: "0.0.0.0",
      proxy: dataOrigin ? {
        "/dashboard": { target: dataOrigin, changeOrigin: true },
        "/healthz": { target: dataOrigin, changeOrigin: true },
      } : undefined,
    },
  }
})
