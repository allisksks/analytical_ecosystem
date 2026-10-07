import { useQuery } from "@tanstack/react-query";
import { api } from "../../shared/api/client";
import type { Schemas } from "../../shared/api/types";

export type Inbox = Schemas["InboxOut"];
export type InboxTask = Schemas["Task"];

export const useInbox = (projectId?: string) =>
  useQuery({
    queryKey: ["inbox", projectId ?? ""],
    queryFn: async () => (await api.GET("/api/v1/inbox", { params: { query: { project_id: projectId! } } })).data!,
    enabled: !!projectId,
    refetchInterval: 60_000,
    staleTime: 15_000,
  });
