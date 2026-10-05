import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";
import type { ParamIn, Schemas } from "../../shared/api/types";
import { API_BASE } from "../../shared/api/client";
import { useI18n } from "../../shared/i18n";
import { formatNumber } from "../../shared/lib/format";
import {
  Badge,
  Button,
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
import { useEmsMutations } from "./api";
import { ParamsEditor } from "./ParamsEditor";

export function NewEventDialog({ projectId, onClose }: { projectId: string; onClose: () => void }) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const m = useEmsMutations();
  const [form, setForm] = useState({
    name: "",
    description: "",
    goal: "",
    question: "",
    category: "",
    app_version: "",
  });
  const [params, setParams] = useState<ParamIn[]>([]);
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });
  return (
    <Modal
      open
      size="xl"
      title={t("ems.newEvent")}
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>{t("common.cancel")}</Button>
          <Button
            variant="primary"
            disabled={!form.name}
            loading={m.create.isPending}
            onClick={() =>
              m.create.mutate(
                { project_id: projectId, ...form, params, metric_keys: [], tags: [], owner: "" },
                {
                  onSuccess: (ev) => {
                    onClose();
                    navigate(`/ems?tab=registry&event=${ev.name}`);
                  },
                },
              )
            }
          >
            {t("common.create")}
          </Button>
        </>
      }
    >
      {m.create.error && <ErrorBox>{m.create.error.message}</ErrorBox>}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
        <Field label={t("ems.goal")} hint="GQM: Goal" className="full">
          <Input value={form.goal} onChange={set("goal")} placeholder="Понять, где новички бросают обучение" />
        </Field>
        <Field label={t("ems.question")} hint="GQM: Question" className="full">
          <Input
            value={form.question}
            onChange={set("question")}
            placeholder="На каком шаге туториала теряем больше всего?"
          />
        </Field>
        <Field label={t("ems.name")} hint="snake_case" required>
          <Input mono value={form.name} onChange={set("name")} placeholder="tutorial_step" />
        </Field>
        <Field label={t("ems.category")}>
          <Input value={form.category} onChange={set("category")} />
        </Field>
        <Field label={t("common.description")} className="full">
          <Textarea value={form.description} onChange={set("description")} style={{ minHeight: 56 }} />
        </Field>
        <div className="full">
          <ParamsEditor value={params} onChange={setParams} />
        </div>
        <Field label={t("ems.appVersion")}>
          <Input value={form.app_version} onChange={set("app_version")} />
        </Field>
      </div>
    </Modal>
  );
}

export function ImportDialog({ projectId, onClose }: { projectId: string; onClose: () => void }) {
  const { t } = useI18n();
  const toast = useToast();
  const m = useEmsMutations();
  const file = useRef<HTMLInputElement>(null);
  const [result, setResult] = useState<Schemas["ImportOut"] | null>(null);
  const template = async () => {
    const { authFetch } = await import("../../shared/api/client");
    const r = await authFetch(new Request(`${API_BASE}/ems/import/template`));
    const url = URL.createObjectURL(await r.blob());
    const a = document.createElement("a");
    a.href = url;
    a.download = "tracking_plan.csv";
    a.click();
  };
  return (
    <Modal
      open
      title={t("ems.import")}
      onClose={onClose}
      footer={<Button onClick={onClose}>{t("common.close")}</Button>}
    >
      <p className="muted" style={{ marginBottom: 12 }}>
        {t("ems.importHint")}
      </p>
      <div style={{ display: "flex", gap: 8 }}>
        <Button onClick={() => void template()}>{t("ems.template")}</Button>
        <input
          ref={file}
          type="file"
          accept=".csv,.xlsx"
          hidden
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f)
              m.importPlan.mutate(
                { projectId, file: f },
                { onSuccess: setResult, onError: (err) => toast.error(err.message) },
              );
            e.target.value = "";
          }}
        />
        <Button variant="primary" loading={m.importPlan.isPending} onClick={() => file.current?.click()}>
          {t("ems.import")}
        </Button>
      </div>
      {result && (
        <div style={{ marginTop: 16 }}>
          <p>
            {t("ems.importResult", {
              c: result.created.length,
              v: result.versioned.length,
              u: result.unchanged.length,
              e: result.errors.length,
            })}
          </p>
          {result.errors.length > 0 && <ErrorBox>{result.errors.join("\n")}</ErrorBox>}
        </div>
      )}
    </Modal>
  );
}

export function DiscoverDialog({ projectId, onClose }: { projectId: string; onClose: () => void }) {
  const { t, locale } = useI18n();
  const toast = useToast();
  const m = useEmsMutations();
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const { mutate: discover } = m.discover;
  useEffect(() => {
    discover(projectId, {
      onSuccess: (rows) => setPicked(new Set(rows.filter((r) => !r.registered).map((r) => r.name))),
    });
  }, [discover, projectId]);
  const rows = m.discover.data ?? [];
  return (
    <Modal
      open
      size="xl"
      title={t("ems.discovered")}
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>{t("common.close")}</Button>
          <Button
            variant="primary"
            disabled={!picked.size}
            loading={m.applyDiscovered.isPending}
            onClick={() =>
              m.applyDiscovered.mutate(
                { project_id: projectId, events: rows.filter((r) => picked.has(r.name)) },
                {
                  onSuccess: (r) => {
                    toast.success(`+${r.created.length}`);
                    onClose();
                  },
                },
              )
            }
          >
            {t("ems.createDrafts", { n: picked.size })}
          </Button>
        </>
      }
    >
      {m.discover.error && <ErrorBox>{m.discover.error.message}</ErrorBox>}
      {m.discover.isPending ? (
        <PageSpinner />
      ) : (
        <Table compact maxHeight={480}>
          <tbody>
            {rows.map((r) => (
              <tr key={r.name}>
                <td>
                  <Checkbox
                    label={<code>{r.name}</code>}
                    disabled={r.registered}
                    checked={picked.has(r.name)}
                    onChange={(e) => {
                      const next = new Set(picked);
                      if (e.target.checked) next.add(r.name);
                      else next.delete(r.name);
                      setPicked(next);
                    }}
                  />
                </td>
                <td style={{ textAlign: "right" }}>{formatNumber(r.count, locale)}</td>
                <td>{r.registered && <Badge tone="pos">{t("ems.registered")}</Badge>}</td>
                <td className="muted" style={{ fontSize: 12 }}>
                  {r.params.map((p) => `${p.name}:${p.type}${p.required ? "*" : ""}`).join(", ")}
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </Modal>
  );
}
