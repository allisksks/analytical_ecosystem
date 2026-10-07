import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../shared/api/client";
import type { FilterIn, Schemas } from "../../shared/api/types";

export interface GlobalFilters {
  date_from?: string;
  date_to?: string;
  filters: FilterIn[];
}

export const biKeys = {
  list: (projectId: string | null, portfolio: boolean) => ["dashboards", portfolio ? "portfolio" : projectId] as const,
  one: (id: string) => ["dashboard", id] as const,
  data: (dashId: string, widgetId: string, f: GlobalFilters, rev: string) =>
    ["widget-data", dashId, widgetId, f, rev] as const,
  templates: ["dashboard-templates"] as const,
  metrics: ["semantic", "metrics"] as const,
  dimensions: ["semantic", "dimensions"] as const,
  values: (key: string, projectId: string | null) => ["semantic", "values", key, projectId] as const,
};

export const useDashboards = (projectId: string | null, portfolio = false) =>
  useQuery({
    queryKey: biKeys.list(projectId, portfolio),
    queryFn: async () =>
      (await api.GET("/api/v1/dashboards", { params: { query: { project_id: projectId ?? undefined, portfolio } } }))
        .data!,
    enabled: portfolio || !!projectId,
  });

export const useDashboard = (id: string | undefined) =>
  useQuery({
    queryKey: biKeys.one(id ?? ""),
    queryFn: async () =>
      (await api.GET("/api/v1/dashboards/{dashboard_id}", { params: { path: { dashboard_id: id! } } })).data!,
    enabled: !!id,
  });

export const useWidgetData = (
  dashId: string,
  widgetId: string,
  filters: GlobalFilters,
  rev: string,
  publicToken?: string,
) =>
  useQuery({
    queryKey: [...biKeys.data(dashId, widgetId, filters, rev), publicToken ?? ""],
    queryFn: async () =>
      publicToken
        ? (
            await api.POST("/api/v1/public/dashboards/{token}/widgets/{widget_id}/data", {
              params: { path: { token: publicToken, widget_id: widgetId } },
              body: filters,
            })
          ).data!
        : (
            await api.POST("/api/v1/dashboards/{dashboard_id}/widgets/{widget_id}/data", {
              params: { path: { dashboard_id: dashId, widget_id: widgetId } },
              body: filters,
            })
          ).data!,
    staleTime: 60_000,
  });

export const useTemplates = () =>
  useQuery({
    queryKey: biKeys.templates,
    queryFn: async () => (await api.GET("/api/v1/dashboards/templates")).data!,
    staleTime: Infinity,
  });

export const useMetrics = () =>
  useQuery({ queryKey: biKeys.metrics, queryFn: async () => (await api.GET("/api/v1/semantic/metrics")).data! });

export const useDimensions = () =>
  useQuery({ queryKey: biKeys.dimensions, queryFn: async () => (await api.GET("/api/v1/semantic/dimensions")).data! });

export const useDimensionValues = (key: string, projectId: string | null, enabled = true) =>
  useQuery({
    queryKey: biKeys.values(key, projectId),
    queryFn: async () =>
      (
        await api.GET("/api/v1/semantic/dimensions/{key}/values", {
          params: { path: { key }, query: { project_id: projectId ?? undefined } },
        })
      ).data!,
    enabled: enabled && !!key,
    staleTime: 5 * 60_000,
  });

export function useBiMutations() {
  const qc = useQueryClient();
  const refreshDash = (id: string) => qc.invalidateQueries({ queryKey: biKeys.one(id) });
  return {
    create: useMutation({
      mutationFn: async (body: Schemas["DashboardIn"]) => (await api.POST("/api/v1/dashboards", { body })).data!,
      onSuccess: () => qc.invalidateQueries({ queryKey: ["dashboards"] }),
    }),
    fromTemplate: useMutation({
      mutationFn: async (body: Schemas["FromTemplateIn"]) =>
        (await api.POST("/api/v1/dashboards/from-template", { body })).data!,
      onSuccess: () => qc.invalidateQueries({ queryKey: ["dashboards"] }),
    }),
    remove: useMutation({
      mutationFn: async (id: string) =>
        api.DELETE("/api/v1/dashboards/{dashboard_id}", { params: { path: { dashboard_id: id } } }),
      onSuccess: () => qc.invalidateQueries({ queryKey: ["dashboards"] }),
    }),
    addWidget: useMutation({
      mutationFn: async ({ dashId, body }: { dashId: string; body: Schemas["WidgetIn"] }) =>
        (
          await api.POST("/api/v1/dashboards/{dashboard_id}/widgets", {
            params: { path: { dashboard_id: dashId } },
            body,
          })
        ).data!,
      onSuccess: (_d, v) => refreshDash(v.dashId),
    }),
    updateWidget: useMutation({
      mutationFn: async ({ id, body }: { id: string; dashId: string; body: Schemas["WidgetPatch"] }) =>
        (await api.PATCH("/api/v1/widgets/{widget_id}", { params: { path: { widget_id: id } }, body })).data!,
      onSuccess: (_d, v) => refreshDash(v.dashId),
    }),
    deleteWidget: useMutation({
      mutationFn: async ({ id }: { id: string; dashId: string }) =>
        api.DELETE("/api/v1/widgets/{widget_id}", { params: { path: { widget_id: id } } }),
      onSuccess: (_d, v) => refreshDash(v.dashId),
    }),
    saveLayout: useMutation({
      mutationFn: async ({ dashId, body }: { dashId: string; body: Schemas["LayoutItem"][] }) =>
        (
          await api.PUT("/api/v1/dashboards/{dashboard_id}/layout", {
            params: { path: { dashboard_id: dashId } },
            body,
          })
        ).data!,
      onSuccess: (d) => qc.setQueryData(biKeys.one(d.id), d),
    }),
    share: useMutation({
      mutationFn: async ({ dashId, ttl }: { dashId: string; ttl: number }) =>
        (
          await api.POST("/api/v1/dashboards/{dashboard_id}/share", {
            params: { path: { dashboard_id: dashId } },
            body: { ttl_days: ttl },
          })
        ).data!,
      onSuccess: (_d, v) => refreshDash(v.dashId),
    }),
    unshare: useMutation({
      mutationFn: async (dashId: string) =>
        api.DELETE("/api/v1/dashboards/{dashboard_id}/share", { params: { path: { dashboard_id: dashId } } }),
      onSuccess: (_d, id) => refreshDash(id),
    }),
    preview: useMutation({
      mutationFn: async (body: Schemas["PreviewIn"]) => (await api.POST("/api/v1/widgets/preview", { body })).data!,
    }),
    semanticQuery: useMutation({
      mutationFn: async (body: Schemas["SemanticQueryIn"]) =>
        (await api.POST("/api/v1/semantic/query", { body })).data!,
    }),
  };
}
