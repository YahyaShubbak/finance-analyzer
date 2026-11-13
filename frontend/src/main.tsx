import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "./index.css";
import App from "./App.tsx";
import { retryQuery } from "./api/client";
import { LanguageProvider } from "./i18n/LanguageProvider";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: retryQuery,
    },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <LanguageProvider>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </QueryClientProvider>
    </LanguageProvider>
  </StrictMode>
);
