import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../shared/api/client";
import type { Schemas } from "../../shared/api/types";

export const emsKeys = {
  all: ["ems"] as const,
  events: (p: string) => ["ems", "events", p] as const,
  event: (id: string) => ["ems", "event", id] as const,
  alerts: (p: string, s: string) => ["ems", "alerts", p, s] as const,
  runs: (p: string) => ["ems", "runs", p] as const,
  gov: (p: string) => ["ems", "gov", p] as const,
  tracking: (p: string) => ["ems", "tracking", p] as const,
  globals: ["ems", "globals"] as const,
  stats: (id: string) => ["ems", "stats", id] as const,
};

export const useEvents = (projectId?: string) =>
  useQuery({
    queryKey: emsKeys.events(projectId ?? ""),
    queryFn: async () => (await api.GET("/api/v1/ems/events", { params: { query: { project_id: projectId! } } })).data!,
    enabled: !!projectId,
  });

export const useEvent = (id?: string) =>
  useQuery({
    queryKey: emsKeys.event(id ?? ""),
    queryFn: async () =>
      (await api.GET("/api/v1/ems/events/{event_id}", { params: { path: { event_id: id! } } })).data!,
    enabled: !!id,
  });

export const useAlerts = (projectId?: string, status = "active") =>
  useQuery({
    queryKey: emsKeys.alerts(projectId ?? "", status),
    queryFn: async () =>
      (await api.GET("/api/v1/ems/alerts", { params: { query: { project_id: projectId!, status } } })).data!,
    enabled: !!projectId,
  });

export const useRuns = (projectId?: string) =>
  useQuery({
    queryKey: emsKeys.runs(projectId ?? ""),
    queryFn: async () =>
      (await api.GET("/api/v1/ems/runs", { params: { query: { project_id: projectId!, limit: 5 } } })).data!,
    enabled: !!projectId,
  });

export const useGovernance = (projectId?: string) =>
  useQuery({
    queryKey: emsKeys.gov(projectId ?? ""),
    queryFn: async () =>
      (await api.GET("/api/v1/ems/governance", { params: { query: { project_id: projectId! } } })).data!,
    enabled: !!projectId,
  });

export const useTracking = (projectId?: string) =>
  useQuery({
    queryKey: emsKeys.tracking(projectId ?? ""),
    queryFn: async () =>
      (await api.GET("/api/v1/ems/tracking/{project_id}", { params: { path: { project_id: projectId! } } })).data ??
      null,
    enabled: !!projectId,
  });

export const useGlobalParams = () =>
  useQuery({ queryKey: emsKeys.globals, queryFn: async () => (await api.GET("/api/v1/ems/global-params")).data! });

export const useEventStats = (id: string, enabled: boolean) =>
  useQuery({
    queryKey: emsKeys.stats(id),
    queryFn: async () =>
      (
        await api.GET("/api/v1/ems/events/{event_id}/stats", {
          params: { path: { event_id: id }, query: { days: 30 } },
        })
      ).data!,
    enabled,
  });

export function useEmsMutations() {
  const qc = useQueryClient();
  const refresh = () => qc.invalidateQueries({ queryKey: emsKeys.all });
  return {
    create: useMutation({
      mutationFn: async (body: Schemas["EventIn"]) => (await api.POST("/api/v1/ems/events", { body })).data!,
      onSuccess: refresh,
    }),
    patch: useMutation({
      mutationFn: async ({ id, body }: { id: string; body: Schemas["EventPatch"] }) =>
        (await api.PATCH("/api/v1/ems/events/{event_id}", { params: { path: { event_id: id } }, body })).data!,
      onSuccess: refresh,
    }),
    propose: useMutation({
      mutationFn: async ({ id, body }: { id: string; body: Schemas["VersionIn"] }) =>
        (await api.POST("/api/v1/ems/events/{event_id}/versions", { params: { path: { event_id: id } }, body })).data!,
      onSuccess: refresh,
    }),
    review: useMutation({
      mutationFn: async ({
        id,
        versionId,
        approve,
        comment,
      }: {
        id: string;
        versionId: string;
        approve: boolean;
        comment: string;
      }) =>
        (
          await api.POST("/api/v1/ems/events/{event_id}/versions/{version_id}/review", {
            params: { path: { event_id: id, version_id: versionId } },
            body: { approve, comment },
          })
        ).data!,
      onSuccess: refresh,
    }),
    status: useMutation({
      mutationFn: async ({ id, status }: { id: string; status: Schemas["StatusIn"]["status"] }) =>
        (
          await api.POST("/api/v1/ems/events/{event_id}/status", {
            params: { path: { event_id: id } },
            body: { status, reason: "" },
          })
        ).data!,
      onSuccess: refresh,
    }),
    comment: useMutation({
      mutationFn: async ({ id, text }: { id: string; text: string }) =>
        (
          await api.POST("/api/v1/ems/events/{event_id}/comments", {
            params: { path: { event_id: id } },
            body: { text },
          })
        ).data!,
      onSuccess: refresh,
    }),
    validate: useMutation({
      mutationFn: async (projectId: string) =>
        (await api.POST("/api/v1/ems/validate/{project_id}", { params: { path: { project_id: projectId } } })).data!,
      onSuccess: refresh,
    }),
    alert: useMutation({
      mutationFn: async ({ id, action }: { id: string; action: "ack" | "resolve" | "reopen" }) =>
        (await api.POST("/api/v1/ems/alerts/{alert_id}/{action}", { params: { path: { alert_id: id, action } } }))
          .data!,
      onSuccess: refresh,
    }),
    tracking: useMutation({
      mutationFn: async ({ projectId, body }: { projectId: string; body: Schemas["TrackingIn"] }) =>
        (await api.PUT("/api/v1/ems/tracking/{project_id}", { params: { path: { project_id: projectId } }, body }))
          .data!,
      onSuccess: refresh,
    }),
    globals: useMutation({
      mutationFn: async (body: Schemas["GlobalParamIn"][]) =>
        (await api.PUT("/api/v1/ems/global-params", { body })).data!,
      onSuccess: refresh,
    }),
    importPlan: useMutation({
      mutationFn: async ({ projectId, file }: { projectId: string; file: File }) =>
        (
          await api.POST("/api/v1/ems/import", {
            params: { query: { project_id: projectId } },
            body: { file: file as unknown as string },
            bodySerializer: (b) => {
              const fd = new FormData();
              fd.append("file", b.file as unknown as Blob);
              return fd;
            },
          })
        ).data!,
      onSuccess: refresh,
    }),
    discover: useMutation({
      mutationFn: async (projectId: string) =>
        (await api.GET("/api/v1/ems/discover", { params: { query: { project_id: projectId } } })).data!,
    }),
    applyDiscovered: useMutation({
      mutationFn: async (body: Schemas["DiscoverApplyIn"]) =>
        (await api.POST("/api/v1/ems/discover/apply", { body })).data!,
      onSuccess: refresh,
    }),
  };
}

export type TrackingDraft = Schemas["TrackingDraftOut"];
export type TrackingDraftItem = Schemas["TrackingDraftItemOut"];

export const useAiDrafts = (projectId?: string) =>
  useQuery({
    queryKey: ["ems", "ai-drafts", projectId ?? ""],
    queryFn: async () =>
      (await api.GET("/api/v1/ems/ai-drafts", { params: { query: { project_id: projectId! } } })).data!,
    enabled: !!projectId,
  });

export const useAiDraft = (id?: string | null) =>
  useQuery({
    queryKey: ["ems", "ai-draft", id ?? ""],
    queryFn: async () =>
      (await api.GET("/api/v1/ems/ai-drafts/{draft_id}", { params: { path: { draft_id: id! } } })).data!,
    enabled: !!id,
  });

export function useAiDraftMutations() {
  const qc = useQueryClient();
  const refresh = () => qc.invalidateQueries({ queryKey: emsKeys.all });
  return {
    create: useMutation({
      mutationFn: async (v: {
        projectId: string;
        file?: File | null;
        text?: string;
        title?: string;
        appVersion?: string;
      }) => {
        const fd = new FormData();
        fd.append("project_id", v.projectId);
        if (v.file) fd.append("file", v.file);
        if (v.text) fd.append("text", v.text);
        if (v.title) fd.append("title", v.title);
        if (v.appVersion) fd.append("app_version", v.appVersion);
        return (
          await api.POST("/api/v1/ems/ai-drafts", {
            body: fd as unknown as Schemas["Body_create_ai_draft_api_v1_ems_ai_drafts_post"],
            bodySerializer: (b) => b as unknown as FormData,
          })
        ).data!;
      },
      onSuccess: refresh,
    }),
    patch: useMutation({
      mutationFn: async (v: { draftId: string; itemId: string; body: Schemas["TrackingDraftItemPatch"] }) =>
        (
          await api.PATCH("/api/v1/ems/ai-drafts/{draft_id}/items/{item_id}", {
            params: { path: { draft_id: v.draftId, item_id: v.itemId } },
            body: v.body,
          })
        ).data!,
      onSuccess: refresh,
    }),
    decide: useMutation({
      mutationFn: async (v: { draftId: string; itemId: string; decision: "accept" | "reject" }) =>
        (
          await api.POST("/api/v1/ems/ai-drafts/{draft_id}/items/{item_id}/{decision}", {
            params: { path: { draft_id: v.draftId, item_id: v.itemId, decision: v.decision } },
          })
        ).data!,
      onSuccess: refresh,
    }),
  };
}
