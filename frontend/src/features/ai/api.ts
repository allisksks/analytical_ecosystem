import { useMutation, useQuery } from "@tanstack/react-query";
import { API_BASE, ApiError, api, authFetch } from "../../shared/api/client";
import type { Schemas } from "../../shared/api/types";

export type AiSource = Schemas["Source"];
export type SqlOut = Schemas["SqlOut"];

export const useAiStatus = () =>
  useQuery({
    queryKey: ["ai", "status"],
    queryFn: async () => (await api.GET("/api/v1/ai/status")).data!,
    staleTime: 60_000,
  });

export interface StreamHandlers {
  onSources: (s: AiSource[]) => void;
  onDelta: (text: string) => void;
  onDone: (interactionId: string) => void;
  onError: (message: string) => void;
}

/** Parses Server-Sent Events from a fetch body: blocks separated by a blank line, "event:" + "data:" lines. */
export function parseSse(buffer: string): { events: { event: string; data: unknown }[]; rest: string } {
  const blocks = buffer.split("\n\n");
  const rest = blocks.pop() ?? "";
  const events = blocks
    .map((b) => {
      let event = "message";
      const data: string[] = [];
      for (const line of b.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
      }
      try {
        return { event, data: JSON.parse(data.join("\n")) as unknown };
      } catch {
        return null;
      }
    })
    .filter((e): e is { event: string; data: unknown } => e !== null);
  return { events, rest };
}

export async function askStream(
  body: { question: string; project_id: string | null },
  h: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const res = await authFetch(
    new Request(`${API_BASE}/ai/ask/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify(body),
      signal,
    }),
  );
  if (!res.ok || !res.body) {
    let problem = {};
    try {
      problem = await res.json();
    } catch {
      /* not json */
    }
    throw new ApiError(res.status, problem);
  }
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    const parsed = parseSse(buffer + value);
    buffer = parsed.rest;
    for (const { event, data } of parsed.events) {
      if (event === "sources") h.onSources(data as AiSource[]);
      else if (event === "delta") h.onDelta(data as string);
      else if (event === "done") h.onDone((data as { interaction_id: string }).interaction_id);
      else if (event === "error") h.onError((data as { message: string }).message);
    }
  }
}

export const useFeedback = () =>
  useMutation({
    mutationFn: async ({ id, rating, comment = "" }: { id: string; rating: -1 | 0 | 1; comment?: string }) =>
      (
        await api.POST("/api/v1/ai/interactions/{interaction_id}/feedback", {
          params: { path: { interaction_id: id } },
          body: { rating, comment },
        })
      ).data!,
  });

export const useGenerateSql = () =>
  useMutation({
    mutationFn: async (body: Schemas["SqlIn"]) => (await api.POST("/api/v1/ai/sql", { body })).data!,
  });

export const useDraftExperiment = () =>
  useMutation({
    mutationFn: async (id: string) =>
      (await api.POST("/api/v1/ai/draft/experiment/{experiment_id}", { params: { path: { experiment_id: id } } }))
        .data!,
  });

export const useDraftWidget = () =>
  useMutation({
    mutationFn: async (body: Schemas["WidgetDraftIn"]) => (await api.POST("/api/v1/ai/draft/widget", { body })).data!,
  });
