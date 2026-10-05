import { Plus } from "lucide-react";
import { useMemo, useState } from "react";
import type { RoleOut } from "../../shared/api/types";
import { useI18n } from "../../shared/i18n";
import {
  Badge,
  Button,
  Card,
  Checkbox,
  ErrorBox,
  Field,
  Input,
  Modal,
  PageSpinner,
  Table,
  Textarea,
  useToast,
} from "../../shared/ui";
import { useAdminMutations, usePermissions, useRoles } from "./api";
import s from "./admin.module.css";

export function RolesSection() {
  const { t } = useI18n();
  const roles = useRoles();
  const [editing, setEditing] = useState<RoleOut | "new" | null>(null);
  if (roles.isPending) return <PageSpinner />;
  return (
    <Card
      title={t("admin.roles")}
      actions={
        <Button variant="primary" icon={<Plus size={16} />} onClick={() => setEditing("new")}>
          {t("admin.newRole")}
        </Button>
      }
    >
      <Table clickable>
        <thead>
          <tr>
            <th>{t("common.name")}</th>
            <th>{t("common.description")}</th>
            <th>{t("admin.permissions")}</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {roles.data?.map((r) => (
            <tr key={r.id} onClick={() => setEditing(r)}>
              <td>
                <strong>{r.name}</strong>
                <div className="muted">
                  <code>{r.key}</code>
                </div>
              </td>
              <td style={{ maxWidth: 420 }}>{r.description}</td>
              <td>{r.permissions.length}</td>
              <td>
                {r.is_builtin ? <Badge>{t("admin.builtin")}</Badge> : <Badge tone="violet">{t("admin.custom")}</Badge>}
              </td>
            </tr>
          ))}
        </tbody>
      </Table>
      {editing && <RoleModal role={editing === "new" ? null : editing} onClose={() => setEditing(null)} />}
    </Card>
  );
}

function RoleModal({ role, onClose }: { role: RoleOut | null; onClose: () => void }) {
  const { t } = useI18n();
  const toast = useToast();
  const perms = usePermissions();
  const m = useAdminMutations();
  const readOnly = role?.is_builtin ?? false;
  const [key, setKey] = useState(role?.key ?? "");
  const [name, setName] = useState(role?.name ?? "");
  const [description, setDescription] = useState(role?.description ?? "");
  const [selected, setSelected] = useState<Set<string>>(new Set(role?.permissions ?? []));
  const [error, setError] = useState<string | null>(null);
  const groups = useMemo(() => {
    const g = new Map<string, string[]>();
    for (const p of perms.data ?? []) {
      const res = p.key.split(":")[0];
      g.set(res, [...(g.get(res) ?? []), p.key]);
    }
    return [...g.entries()];
  }, [perms.data]);
  const toggle = (k: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      return next;
    });
  const save = async () => {
    setError(null);
    try {
      const permissions = [...selected];
      if (role) await m.updateRole.mutateAsync({ id: role.id, body: { name, description, permissions } });
      else await m.createRole.mutateAsync({ key, name, description, permissions });
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
      title={role ? role.name : t("admin.newRole")}
      onClose={onClose}
      footer={
        <>
          {role && !readOnly && (
            <Button
              variant="danger"
              onClick={() =>
                m.deleteRole.mutate(role.id, {
                  onSuccess: onClose,
                  onError: (e) => setError(e.message),
                })
              }
            >
              {t("common.delete")}
            </Button>
          )}
          <Button onClick={onClose}>{t("common.close")}</Button>
          {!readOnly && (
            <Button variant="primary" onClick={() => void save()} disabled={!name || (!role && !key)}>
              {t("common.save")}
            </Button>
          )}
        </>
      }
    >
      {error && <ErrorBox>{error}</ErrorBox>}
      <div className={s.formGrid}>
        <Field label={t("admin.key")} hint="a-z, 0-9, _">
          <Input value={key} disabled={!!role} onChange={(e) => setKey(e.target.value)} mono />
        </Field>
        <Field label={t("common.name")}>
          <Input value={name} disabled={readOnly} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label={t("common.description")} className={s.full}>
          <Textarea value={description} disabled={readOnly} onChange={(e) => setDescription(e.target.value)} />
        </Field>
        <div className={s.full}>
          <Field label={`${t("admin.permissions")} · ${selected.size}`}>
            <div className={s.permGrid}>
              {groups.map(([res, keys]) => (
                <div key={res} style={{ display: "contents" }}>
                  <div className={s.permGroup}>{res}</div>
                  {keys.map((k) => (
                    <Checkbox
                      key={k}
                      label={<code>{k}</code>}
                      checked={selected.has(k)}
                      disabled={readOnly}
                      onChange={() => toggle(k)}
                    />
                  ))}
                </div>
              ))}
            </div>
          </Field>
        </div>
      </div>
    </Modal>
  );
}
