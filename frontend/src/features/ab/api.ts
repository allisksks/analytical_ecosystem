import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../shared/api/client";
import type { Schemas } from "../../shared/api/types";

export type Experiment = Schemas["ExperimentOut"];
export type ExperimentSummary = Schemas["ExperimentSummary"];
export type ExperimentIn = Schemas["ExperimentIn"];
export type ExperimentResult = Schemas["ExperimentResult"];
export type MetricResult = Schemas["MetricResult"];
export type Comparison = Schemas["Comparison"];
export type MetricTemplate = Schemas["MetricTemplateOut"];
export type ExpStatus = ExperimentSummary["status"];

export const abKeys = {
  all: ["ab"] as const,
  list: (p: string) => ["ab", "list", p] as const,
  one: (id: string) => ["ab", "one", id] as const,
  templates: ["ab", "templates"] as const,
  baseline: (p: string, s: string, m: string) => ["ab", "baseline", p, s, m] as const,
};

export const useExperiments = (projectId?: string) =>
  useQuery({
    queryKey: abKeys.list(projectId ?? ""),
    queryFn: async () =>
      (await api.GET("/api/v1/experiments", { params: { query: { project_id: projectId! } } })).data!,
    enabled: !!projectId,
  });

export const useExperiment = (id?: string) =>
  useQuery({
    queryKey: abKeys.one(id ?? ""),
    queryFn: async () =>
      (await api.GET("/api/v1/experiments/{experiment_id}", { params: { path: { experiment_id: id! } } })).data!,
    enabled: !!id,
  });

export const useTemplates = () =>
  useQuery({
    queryKey: abKeys.templates,
    queryFn: async () => (await api.GET("/api/v1/experiments/metrics")).data!,
    staleTime: Infinity,
  });

export const useBaseline = (projectId?: string, sourceId?: string | null, metricKey?: string) =>
  useQuery({
    queryKey: abKeys.baseline(projectId ?? "", sourceId ?? "", metricKey ?? ""),
    queryFn: async () => {
      const r = await api.GET("/api/v1/experiments/baseline", {
        params: { query: { project_id: projectId!, source_id: sourceId!, metric_key: metricKey! } },
      });
      return r.data ?? null;
    },
    enabled: !!projectId && !!sourceId && !!metricKey,
    staleTime: 10 * 60_000,
    retry: false,
  });

export const usePower = (body: Schemas["PowerIn"] | null) =>
  useQuery({
    queryKey: ["ab", "power", body],
    queryFn: async () => (await api.POST("/api/v1/experiments/power", { body: body! })).data ?? null,
    enabled: !!body,
    retry: false,
  });

export function useAbMutations() {
  const qc = useQueryClient();
  const refresh = () => qc.invalidateQueries({ queryKey: abKeys.all });
  const path = (id: string) => ({ params: { path: { experiment_id: id } } });
  return {
    create: useMutation({
      mutationFn: async (body: ExperimentIn) => (await api.POST("/api/v1/experiments", { body })).data!,
      onSuccess: refresh,
    }),
    patch: useMutation({
      mutationFn: async ({ id, body }: { id: string; body: Schemas["ExperimentPatch"] }) =>
        (await api.PATCH("/api/v1/experiments/{experiment_id}", { ...path(id), body })).data!,
      onSuccess: refresh,
    }),
    transition: useMutation({
      mutationFn: async ({ id, to, comment = "" }: { id: string; to: ExpStatus; comment?: string }) =>
        (await api.POST("/api/v1/experiments/{experiment_id}/transition", { ...path(id), body: { to, comment } }))
          .data!,
      onSuccess: refresh,
    }),
    recalculate: useMutation({
      mutationFn: async (id: string) =>
        (await api.POST("/api/v1/experiments/{experiment_id}/recalculate", path(id))).data!,
      onSuccess: refresh,
    }),
    decide: useMutation({
      mutationFn: async ({ id, body }: { id: string; body: Schemas["DecisionIn"] }) =>
        (await api.POST("/api/v1/experiments/{experiment_id}/decision", { ...path(id), body })).data!,
      onSuccess: refresh,
    }),
    saveToKb: useMutation({
      mutationFn: async (id: string) => (await api.POST("/api/v1/experiments/{experiment_id}/kb", path(id))).data!,
      onSuccess: refresh,
    }),
  };
}
