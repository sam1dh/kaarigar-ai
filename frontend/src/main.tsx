import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClientProvider } from "@tanstack/react-query";
import { registerSW } from "virtual:pwa-register";

// Fonts downloaded at app start (section 7.5): Anek Latin (headings) +
// IBM Plex Sans (body). Every other script loads on demand via
// src/i18n/fonts.ts when its language is chosen.
import "@fontsource-variable/anek-latin";
import "@fontsource-variable/ibm-plex-sans";

import "@/i18n"; // i18next init (reads localStorage pill choice)
import "./index.css";
import Router from "./app/router";
import { queryClient } from "./lib/queryClient";

registerSW({ immediate: true });

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Router />
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
);
