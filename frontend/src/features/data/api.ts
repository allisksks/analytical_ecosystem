import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../shared/api/client";
import type { Schemas } from "../../shared/api/types";

export const dataKeys = {
  types: ["connectors", "types"] as const,
  sources: ["sources"] as const,
  catalog: (id: string) => ["catalog", id] as const,
  history: ["query", "history"] as const,
  saved: (projectId?: string) => ["saved-queries", projectId ?? "all"] as const,
};

export const useConnectorTypes = () =>
  useQuery({
    queryKey: dataKeys.types,
    queryFn: async () => (await api.GET("/api/v1/connectors/types")).data!,
    staleTime: Infinity,
  });

export const useSources = () =>
  useQuery({ queryKey: dataKeys.sources, queryFn: async () => (await api.GET("/api/v1/sources")).data! });

export const useCatalog = (sourceId: string | undefined) =>
  useQuery({
    queryKey: dataKeys.catalog(sourceId ?? ""),
    queryFn: async () =>
      (await api.GET("/api/v1/sources/{source_id}/catalog", { params: { path: { source_id: sourceId! } } })).data!,
    enabled: !!sourceId,
  });

export const useHistory = () =>
  useQuery({ queryKey: dataKeys.history, queryFn: async () => (await api.GET("/api/v1/query/history")).data! });

export const useSavedQueries = (projectId?: string) =>
  useQuery({
    queryKey: dataKeys.saved(projectId),
    queryFn: async () =>
      (await api.GET("/api/v1/saved-queries", { params: { query: { project_id: projectId } } })).data!,
  });

export function useDataMutations() {
  const qc = useQueryClient();
  const sourcesChanged = () => qc.invalidateQueries({ queryKey: dataKeys.sources });
  return {
    testConfig: useMutation({
      mutationFn: async (body: Schemas["SourceTestIn"]) => (await api.POST("/api/v1/sources/test", { body })).data!,
    }),
    create: useMutation({
      mutationFn: async (body: Schemas["SourceIn"]) => (await api.POST("/api/v1/sources", { body })).data!,
      onSuccess: sourcesChanged,
    }),
    update: useMutation({
      mutationFn: async ({ id, body }: { id: string; body: Schemas["SourcePatch"] }) =>
        (await api.PATCH("/api/v1/sources/{source_id}", { params: { path: { source_id: id } }, body })).data!,
      onSuccess: sourcesChanged,
    }),
    remove: useMutation({
      mutationFn: async (id: string) =>
        api.DELETE("/api/v1/sources/{source_id}", { params: { path: { source_id: id } } }),
      onSuccess: sourcesChanged,
    }),
    test: useMutation({
      mutationFn: async (id: string) =>
        (await api.POST("/api/v1/sources/{source_id}/test", { params: { path: { source_id: id } } })).data!,
      onSuccess: sourcesChanged,
    }),
    refresh: useMutation({
      mutationFn: async (id: string) =>
        (await api.POST("/api/v1/sources/{source_id}/refresh-catalog", { params: { path: { source_id: id } } })).data!,
      onSuccess: (_d, id) => {
        void sourcesChanged();
        void qc.invalidateQueries({ queryKey: dataKeys.catalog(id) });
      },
    }),
    sync: useMutation({
      mutationFn: async (id: string) =>
        (await api.POST("/api/v1/sources/{source_id}/sync", { params: { path: { source_id: id } } })).data!,
      onSuccess: (_d, id) => {
        void sourcesChanged();
        void qc.invalidateQueries({ queryKey: dataKeys.catalog(id) });
      },
    }),
    upload: useMutation({
      mutationFn: async ({ id, file }: { id: string; file: File }) =>
        (
          await api.POST("/api/v1/sources/{source_id}/files", {
            params: { path: { source_id: id } },
            body: { file: file as unknown as string },
            bodySerializer: (b) => {
              const fd = new FormData();
              fd.append("file", b.file as unknown as Blob);
              return fd;
            },
          })
        ).data!,
      onSuccess: (_d, { id }) => {
        void sourcesChanged();
        void qc.invalidateQueries({ queryKey: dataKeys.catalog(id) });
      },
    }),
    purge: useMutation({
      mutationFn: async (id: string) =>
        api.POST("/api/v1/sources/{source_id}/purge-cache", { params: { path: { source_id: id } } }),
    }),
    patchTable: useMutation({
      mutationFn: async ({ id, body }: { id: string; body: Schemas["TablePatch"]; sourceId: string }) =>
        (await api.PATCH("/api/v1/catalog/tables/{table_id}", { params: { path: { table_id: id } }, body })).data!,
      onSuccess: (_d, v) => qc.invalidateQueries({ queryKey: dataKeys.catalog(v.sourceId) }),
    }),
    patchColumn: useMutation({
      mutationFn: async ({ id, body }: { id: string; body: Schemas["ColumnPatch"]; sourceId: string }) =>
        (await api.PATCH("/api/v1/catalog/columns/{column_id}", { params: { path: { column_id: id } }, body })).data!,
      onSuccess: (_d, v) => qc.invalidateQueries({ queryKey: dataKeys.catalog(v.sourceId) }),
    }),
    run: useMutation({
      mutationFn: async (body: Schemas["RunIn"]) => (await api.POST("/api/v1/query/run", { body })).data!,
      onSettled: () => qc.invalidateQueries({ queryKey: dataKeys.history }),
    }),
    saveQuery: useMutation({
      mutationFn: async (body: Schemas["SavedQueryIn"]) => (await api.POST("/api/v1/saved-queries", { body })).data!,
      onSuccess: () => qc.invalidateQueries({ queryKey: ["saved-queries"] }),
    }),
    deleteSaved: useMutation({
      mutationFn: async (id: string) =>
        api.DELETE("/api/v1/saved-queries/{sq_id}", { params: { path: { sq_id: id } } }),
      onSuccess: () => qc.invalidateQueries({ queryKey: ["saved-queries"] }),
    }),
  };
}
