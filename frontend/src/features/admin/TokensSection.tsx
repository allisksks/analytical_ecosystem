import { Plus } from "lucide-react";
import { useState } from "react";
import { useI18n } from "../../shared/i18n";
import { formatDateTime } from "../../shared/lib/format";
import {
  Badge,
  Button,
  Card,
  ErrorBox,
  Field,
  Input,
  Modal,
  PageSpinner,
  Select,
  Table,
  Textarea,
} from "../../shared/ui";
import { useAdminMutations, useAllProjects, useTokens } from "./api";
import s from "./admin.module.css";

export function TokensSection() {
  const { t, locale } = useI18n();
  const tokens = useTokens();
  const projects = useAllProjects();
  const m = useAdminMutations();
  const [creating, setCreating] = useState(false);
  if (tokens.isPending) return <PageSpinner />;
  return (
    <Card
      title={t("admin.tokens")}
      actions={
        <Button variant="primary" icon={<Plus size={16} />} onClick={() => setCreating(true)}>
          {t("admin.newToken")}
        </Button>
      }
    >
      <Table>
        <thead>
          <tr>
            <th>{t("common.name")}</th>
            <th>{t("admin.permissions")}</th>
            <th>{t("common.project")}</th>
            <th>{t("admin.expires")}</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {tokens.data?.map((tk) => (
            <tr key={tk.id}>
              <td>
                <strong>{tk.name}</strong>
                <div className="muted">
                  <code>apt_{tk.prefix}_…</code>
                </div>
              </td>
              <td>
                <code>{tk.permissions.join(", ")}</code>
              </td>
              <td>{projects.data?.find((p) => p.id === tk.project_id)?.name ?? t("admin.orgWide")}</td>
              <td>{formatDateTime(tk.expires_at, locale)}</td>
              <td>
                {tk.revoked_at ? (
                  <Badge tone="neg">{t("admin.revoked")}</Badge>
                ) : (
                  <Button size="sm" variant="ghost" onClick={() => m.revokeToken.mutate(tk.id)}>
                    {t("admin.revoke")}
                  </Button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </Table>
      {creating && <TokenModal onClose={() => setCreating(false)} />}
    </Card>
  );
}

function TokenModal({ onClose }: { onClose: () => void }) {
  const { t } = useI18n();
  const projects = useAllProjects();
  const m = useAdminMutations();
  const [name, setName] = useState("");
  const [perms, setPerms] = useState("events:view, events:download");
  const [projectId, setProjectId] = useState("");
  const [ttl, setTtl] = useState(90);
  const [plain, setPlain] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const create = async () => {
    setError(null);
    try {
      const res = await m.createToken.mutateAsync({
        name,
        permissions: perms.split(/[\s,]+/).filter(Boolean),
        project_id: projectId || null,
        ttl_days: ttl,
      });
      setPlain(res.token);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };
  return (
    <Modal
      open
      title={t("admin.newToken")}
      onClose={onClose}
      footer={
        plain ? (
          <Button variant="primary" onClick={onClose}>
            {t("common.close")}
          </Button>
        ) : (
          <>
            <Button onClick={onClose}>{t("common.cancel")}</Button>
            <Button variant="primary" onClick={() => void create()} disabled={!name} loading={m.createToken.isPending}>
              {t("common.create")}
            </Button>
          </>
        )
      }
    >
      {error && <ErrorBox>{error}</ErrorBox>}
      {plain ? (
        <Field label={t("admin.tokenCreated")}>
          <div className={s.tokenBox}>{plain}</div>
        </Field>
      ) : (
        <div className={s.formGrid}>
          <Field label={t("common.name")} className={s.full}>
            <Input value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field label={t("admin.permissions")} className={s.full}>
            <Textarea value={perms} onChange={(e) => setPerms(e.target.value)} mono />
          </Field>
          <Field label={t("common.project")}>
            <Select value={projectId} onChange={(e) => setProjectId(e.target.value)}>
              <option value="">{t("admin.orgWide")}</option>
              {projects.data?.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field label={t("admin.ttlDays")}>
            <Input type="number" min={1} max={365} value={ttl} onChange={(e) => setTtl(Number(e.target.value))} />
          </Field>
        </div>
      )}
    </Modal>
  );
}
