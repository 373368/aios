import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";

import { WorkspaceI18nProvider } from "./features/personal-workspace/i18n";
import { StarfieldBackground } from "./components/starfield-background";
import { AiosShell } from "./components/aios-shell";
import { WorkflowsPanel } from "./components/workflows-panel";
import { router } from "./router";
import "./styles.css";

const root = document.getElementById("root");

if (!root) {
  throw new Error("Root element not found");
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
      staleTime: 15_000,
    },
  },
});

createRoot(root).render(
  <QueryClientProvider client={queryClient}>
    <StarfieldBackground />
    <WorkspaceI18nProvider>
      <AiosShell workspace={<RouterProvider router={router} />} workflows={<WorkflowsPanel />} />
    </WorkspaceI18nProvider>
  </QueryClientProvider>,
);
