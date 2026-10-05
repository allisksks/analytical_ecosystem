import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import type { Schemas, UserOut } from "../../shared/api/types";
import { useI18n } from "../../shared/i18n";
import { formatDateTime } from "../../shared/lib/format";
import {
  Badge,
  Button,
  Card,
  ErrorBox,
  Field,
  IconButton,
  Input,
  Modal,
  PageSpinner,
  Select,
  Switch,
  Table,
  useToast,
} from "../../shared/ui";
import { useAdminMutations, useAllProjects, useRoles, useUsers } from "./api";
import s from "./admin.module.css";

type Membership = Schemas["MembershipIn"];

export function UsersSection() {
  const { t, locale } = useI18n();
  const users = useUsers();
  const projects = useAllProjects();
  const [editing, setEditing] = useState<UserOut | "new" | null>(null);
  const projectName = (id?: string | null) =>
    id ? (projects.data?.find((p) => p.id === id)?.name ?? "?") : t("admin.orgWide");
  if (users.isPending) return <PageSpinner />;
  return (
    <Card padded={false}>
      <div className={s.toolbar} style={{ padding: "16px 20px 0" }}>
        <h2>{t("admin.users")}</h2>
        <Button variant="primary" icon={<Plus size={16} />} onClick={() => setEditing("new")}>
          {t("admin.newUser")}
        </Button>
      </div>
      <div style={{ padding: 20 }}>
        <Table clickable>
          <thead>
            <tr>
              <th>{t("common.name")}</th>
              <th>E-mail</th>
              <th>{t("admin.roles_")}</th>
              <th>{t("admin.mfa")}</th>
              <th>{t("admin.lastLogin")}</th>
              <th>{t("common.status")}</th>
            </tr>
          </thead>
          <tbody>
            {users.data?.map((u) => (
              <tr key={u.id} onClick={() => setEditing(u)}>
                <td>
                  <strong>{u.name}</strong>
                </td>
                <td>{u.email}</td>
                <td>
                  <div className={s.chips}>
                    {u.memberships.map((m, i) => (
                      <Badge key={i} tone={m.project_id ? "info" : "violet"}>
                        {m.role_name} · {projectName(m.project_id)}
                      </Badge>
                    ))}
                  </div>
                </td>
                <td>{u.totp_enabled ? <Badge tone="pos">on</Badge> : <Badge>off</Badge>}</td>
                <td>{formatDateTime(u.last_login_at, locale)}</td>
                <td>
                  {u.is_active ? (
                    <Badge tone="pos" dot>
                      {t("admin.active")}
                    </Badge>
                  ) : (
                    <Badge tone="neg" dot>
                      {t("admin.disabled")}
                    </Badge>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
      </div>
      {editing && <UserModal user={editing === "new" ? null : editing} onClose={() => setEditing(null)} />}
    </Card>
  );
}

function UserModal({ user, onClose }: { user: UserOut | null; onClose: () => void }) {
  const { t } = useI18n();
  const toast = useToast();
  const roles = useRoles();
  const projects = useAllProjects();
  const m = useAdminMutations();
  const [name, setName] = useState(user?.name ?? "");
  const [email, setEmail] = useState(user?.email ?? "");
  const [password, setPassword] = useState("");
  const [active, setActive] = useState(user?.is_active ?? true);
  const [expires, setExpires] = useState(user?.access_expires_at?.slice(0, 10) ?? "");
  const [members, setMembers] = useState<Membership[]>(
    user?.memberships.map((x) => ({ role_key: x.role_key, project_id: x.project_id })) ?? [
      { role_key: "analyst", project_id: null },
    ],
  );
  const [error, setError] = useState<string | null>(null);
  const busy = m.createUser.isPending || m.updateUser.isPending || m.setMemberships.isPending;

  const save = async () => {
    setError(null);
    try {
      const access_expires_at = expires ? new Date(expires).toISOString() : null;
      if (user) {
        await m.updateUser.mutateAsync({
          id: user.id,
          body: { name, is_active: active, access_expires_at, ...(password ? { password } : {}) },
        });
        await m.setMemberships.mutateAsync({ id: user.id, body: members });
      } else {
        await m.createUser.mutateAsync({
          email,
          name,
          password: password || null,
          access_expires_at,
          memberships: members,
        });
      }
      toast.success(t("admin.saved"));
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <Modal
      open
      size="lg"
      title={user ? user.name : t("admin.newUser")}
      onClose={onClose}
      footer={
        <>
          {user?.totp_enabled && (
            <Button variant="ghost" onClick={() => m.resetMfa.mutate(user.id)}>
              {t("admin.resetMfa")}
            </Button>
          )}
          <Button onClick={onClose}>{t("common.cancel")}</Button>
          <Button variant="primary" loading={busy} onClick={() => void save()} disabled={!name || !email}>
            {t("common.save")}
          </Button>
        </>
      }
    >
      {error && <ErrorBox>{error}</ErrorBox>}
      <div className={s.formGrid} style={{ marginTop: error ? 12 : 0 }}>
        <Field label={t("common.name")} required>
          <Input value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="E-mail" required>
          <Input type="email" value={email} disabled={!!user} onChange={(e) => setEmail(e.target.value)} />
        </Field>
        <Field label={t("admin.password")}>
          <Input
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </Field>
        <Field label={t("admin.accessUntil")}>
          <Input type="date" value={expires} onChange={(e) => setExpires(e.target.value)} />
        </Field>
        {user && <Switch checked={active} onChange={setActive} label={t("admin.active")} />}
        <div className={s.full}>
          <Field label={t("admin.roles_")}>
            <div>
              {members.map((mb, i) => (
                <div key={i} className={s.memberRow}>
                  <Select
                    aria-label={t("admin.roles_")}
                    value={mb.role_key}
                    onChange={(e) =>
                      setMembers(members.map((x, j) => (j === i ? { ...x, role_key: e.target.value } : x)))
                    }
                  >
                    {roles.data?.map((r) => (
                      <option key={r.id} value={r.key}>
                        {r.name}
                      </option>
                    ))}
                  </Select>
                  <Select
                    aria-label={t("common.project")}
                    value={mb.project_id ?? ""}
                    onChange={(e) =>
                      setMembers(members.map((x, j) => (j === i ? { ...x, project_id: e.target.value || null } : x)))
                    }
                  >
                    <option value="">{t("admin.orgWide")}</option>
                    {projects.data?.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
                      </option>
                    ))}
                  </Select>
                  <IconButton label={t("common.delete")} onClick={() => setMembers(members.filter((_, j) => j !== i))}>
                    <Trash2 size={16} />
                  </IconButton>
                </div>
              ))}
              <Button
                size="sm"
                icon={<Plus size={14} />}
                onClick={() =>
                  setMembers([...members, { role_key: "analyst", project_id: projects.data?.[0]?.id ?? null }])
                }
              >
                {t("admin.addRole")}
              </Button>
            </div>
          </Field>
        </div>
      </div>
    </Modal>
  );
}
