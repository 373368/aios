import {
  Navigate,
  Outlet,
  createRootRoute,
  createRoute,
  createRouter,
} from "@tanstack/react-router";
import { z } from "zod";

import { DashboardPage } from "./views/dashboard-page";
import { BenchmarkStudyPage } from "./views/benchmark-study-page";

const searchSchema = z.object({
  goalId: z.string().optional().default(""),
  statusUrl: z.string().optional().default(""),
});

const benchmarkStudySearchSchema = z.object({
  dashboardUrl: z.string().optional().default(""),
  view: z.enum(["campaign", "arms", "cases", "runs"]).optional().default("campaign"),
  runId: z.string().optional().default(""),
});

export const rootRoute = createRootRoute({
  component: () => <Outlet />,
});

export const dashboardRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  validateSearch: (search) => searchSchema.parse(search),
  component: DashboardPage,
});

export const benchmarkStudyRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/benchmarks/study",
  validateSearch: (search) => benchmarkStudySearchSchema.parse(search),
  component: BenchmarkStudyPage,
});

const routeTree = rootRoute.addChildren([
  dashboardRoute,
  benchmarkStudyRoute,
]);

function routerBasepathFromViteBase(baseUrl: string) {
  if (!baseUrl || baseUrl === "/" || baseUrl === "./") {
    return "/";
  }
  const withLeadingSlash = baseUrl.startsWith("/") ? baseUrl : `/${baseUrl}`;
  return withLeadingSlash.replace(/\/+$/, "") || "/";
}

export const router = createRouter({
  routeTree,
  basepath: routerBasepathFromViteBase(import.meta.env.BASE_URL),
  trailingSlash: "preserve",
});

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
