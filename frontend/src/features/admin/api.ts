import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../shared/api/client";
import type { Schemas } from "../../shared/api/types";

export const adminKeys = {
  users: ["admin", "users"] as const,
  roles: ["admin", "roles"] as const,
  permissions: ["admin", "permissions"] as const,
  projects: ["projects", "all"] as const,
  tokens: ["admin", "tokens"] as const,
  audit: (f: object) => ["admin", "audit", f] as const,
};

export const useUsers = () =>
  useQuery({ queryKey: adminKeys.users, queryFn: async () => (await api.GET("/api/v1/admin/users")).data! });
export const useRoles = () =>
  useQuery({ queryKey: adminKeys.roles, queryFn: async () => (await api.GET("/api/v1/admin/roles")).data! });
export const usePermissions = () =>
  useQuery({
    queryKey: adminKeys.permissions,
    queryFn: async () => (await api.GET("/api/v1/admin/permissions")).data!,
    staleTime: Infinity,
  });
export const useAllProjects = () =>
  useQuery({
    queryKey: adminKeys.projects,
    queryFn: async () => (await api.GET("/api/v1/projects", { params: { query: { include_archived: true } } })).data!,
  });
export const useTokens = () =>
  useQuery({ queryKey: adminKeys.tokens, queryFn: async () => (await api.GET("/api/v1/admin/tokens")).data! });
export const useAudit = (filters: { action?: string; offset?: number }) =>
  useQuery({
    queryKey: adminKeys.audit(filters),
    queryFn: async () => (await api.GET("/api/v1/admin/audit", { params: { query: { ...filters, limit: 50 } } })).data!,
    placeholderData: (prev) => prev,
  });

export function useAdminMutations() {
  const qc = useQueryClient();
  const inv = (...keys: readonly (readonly string[])[]) => keys.forEach((k) => qc.invalidateQueries({ queryKey: k }));
  return {
    createUser: useMutation({
      mutationFn: async (body: Schemas["UserIn"]) => (await api.POST("/api/v1/admin/users", { body })).data!,
      onSuccess: () => inv(adminKeys.users),
    }),
    updateUser: useMutation({
      mutationFn: async ({ id, body }: { id: string; body: Schemas["UserPatch"] }) =>
        (await api.PATCH("/api/v1/admin/users/{user_id}", { params: { path: { user_id: id } }, body })).data!,
      onSuccess: () => inv(adminKeys.users),
    }),
    setMemberships: useMutation({
      mutationFn: async ({ id, body }: { id: string; body: Schemas["MembershipIn"][] }) =>
        (await api.PUT("/api/v1/admin/users/{user_id}/memberships", { params: { path: { user_id: id } }, body })).data!,
      onSuccess: () => inv(adminKeys.users),
    }),
    resetMfa: useMutation({
      mutationFn: async (id: string) =>
        (await api.POST("/api/v1/admin/users/{user_id}/reset-mfa", { params: { path: { user_id: id } } })).data!,
      onSuccess: () => inv(adminKeys.users),
    }),
    createRole: useMutation({
      mutationFn: async (body: Schemas["RoleIn"]) => (await api.POST("/api/v1/admin/roles", { body })).data!,
      onSuccess: () => inv(adminKeys.roles),
    }),
    updateRole: useMutation({
      mutationFn: async ({ id, body }: { id: string; body: Schemas["RolePatch"] }) =>
        (await api.PATCH("/api/v1/admin/roles/{role_id}", { params: { path: { role_id: id } }, body })).data!,
      onSuccess: () => inv(adminKeys.roles),
    }),
    deleteRole: useMutation({
      mutationFn: async (id: string) =>
        api.DELETE("/api/v1/admin/roles/{role_id}", { params: { path: { role_id: id } } }),
      onSuccess: () => inv(adminKeys.roles),
    }),
    createProject: useMutation({
      mutationFn: async (body: Schemas["ProjectIn"]) => (await api.POST("/api/v1/projects", { body })).data!,
      onSuccess: () => inv(adminKeys.projects, ["me"]),
    }),
    updateProject: useMutation({
      mutationFn: async ({ id, body }: { id: string; body: Schemas["ProjectPatch"] }) =>
        (await api.PATCH("/api/v1/projects/{project_id}", { params: { path: { project_id: id } }, body })).data!,
      onSuccess: () => inv(adminKeys.projects),
    }),
    createToken: useMutation({
      mutationFn: async (body: Schemas["ServiceTokenIn"]) => (await api.POST("/api/v1/admin/tokens", { body })).data!,
      onSuccess: () => inv(adminKeys.tokens),
    }),
    revokeToken: useMutation({
      mutationFn: async (id: string) =>
        api.DELETE("/api/v1/admin/tokens/{token_id}", { params: { path: { token_id: id } } }),
      onSuccess: () => inv(adminKeys.tokens),
    }),
  };
}
