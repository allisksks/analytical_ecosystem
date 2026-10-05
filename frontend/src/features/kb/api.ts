import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../shared/api/client";
import type { Schemas } from "../../shared/api/types";

export interface KbQuery {
  q: string;
  type?: string;
  tag?: string[];
  project_id?: string;
  sort: "relevance" | "newest";
}

export const useKbSearch = (p: KbQuery) =>
  useQuery({
    queryKey: ["kb", "search", p],
    queryFn: async () =>
      (
        await api.GET("/api/v1/kb", {
          params: {
            query: {
              q: p.q,
              type: p.type ? [p.type] : undefined,
              tag: p.tag,
              project_id: p.project_id,
              sort: p.sort,
              limit: 60,
            },
          },
        })
      ).data!,
    placeholderData: keepPreviousData,
  });

export const useKbItem = (id: string | undefined) =>
  useQuery({
    queryKey: ["kb", "item", id],
    queryFn: async () => (await api.GET("/api/v1/kb/{item_id}", { params: { path: { item_id: id! } } })).data!,
    enabled: !!id,
  });

export const useKbVersions = (id: string, enabled: boolean) =>
  useQuery({
    queryKey: ["kb", "versions", id],
    queryFn: async () => (await api.GET("/api/v1/kb/{item_id}/versions", { params: { path: { item_id: id } } })).data!,
    enabled,
  });

export const useKbTemplates = () =>
  useQuery({
    queryKey: ["kb", "templates"],
    queryFn: async () => (await api.GET("/api/v1/kb/templates")).data!,
    staleTime: Infinity,
  });

export function useKbMutations() {
  const qc = useQueryClient();
  const changed = () => qc.invalidateQueries({ queryKey: ["kb"] });
  return {
    create: useMutation({
      mutationFn: async (body: Schemas["ItemIn"]) => (await api.POST("/api/v1/kb", { body })).data!,
      onSuccess: changed,
    }),
    update: useMutation({
      mutationFn: async ({ id, body }: { id: string; body: Schemas["ItemPatch"] }) =>
        (await api.PATCH("/api/v1/kb/{item_id}", { params: { path: { item_id: id } }, body })).data!,
      onSuccess: changed,
    }),
    comment: useMutation({
      mutationFn: async ({ id, text }: { id: string; text: string }) =>
        (await api.POST("/api/v1/kb/{item_id}/comments", { params: { path: { item_id: id } }, body: { text } })).data!,
      onSuccess: changed,
    }),
    attach: useMutation({
      mutationFn: async ({ id, file }: { id: string; file: File }) =>
        (
          await api.POST("/api/v1/kb/{item_id}/attachments", {
            params: { path: { item_id: id } },
            body: { file: file as unknown as string },
            bodySerializer: (b) => {
              const fd = new FormData();
              fd.append("file", b.file as unknown as Blob);
              return fd;
            },
          })
        ).data!,
      onSuccess: changed,
    }),
  };
}
