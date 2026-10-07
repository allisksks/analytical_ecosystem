import { RefreshCw, Trash2, Upload } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import type { ConnectorType, Schemas, Source } from "../../shared/api/types";
import { useI18n } from "../../shared/i18n";
import { Badge, Button, Checkbox, ErrorBox, Field, Input, Modal, useToast } from "../../shared/ui";
import { useAuth, useCan } from "../auth/AuthProvider";
import { JsonSchemaForm } from "./JsonSchemaForm";
import { defaultsFor, type FormValue, type ObjectSchema } from "./schemaDefaults";
import { useConnectorTypes, useDataMutations } from "./api";
import s from "./data.module.css";
import { typeIcon } from "./typeIcon";

type TestOut = Schemas["TestOut"];

function errorText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

export function SourceDialog({ source, onClose }: { source: Source | null; onClose: () => void }) {
  const { t } = useI18n();
  const types = useConnectorTypes();
  const [type, setType] = useState<ConnectorType | null>(null);
  const current = source ? (types.data?.find((x) => x.type === source.type) ?? null) : type;

  if (!source && !current) {
    return (
      <Modal open size="lg" title={t("data.chooseType")} onClose={onClose}>
        <div className={s.typeGrid}>
          {types.data?.map((ct) => (
            <button key={ct.type} className={s.typeBtn} disabled={!ct.available} onClick={() => setType(ct)}>
              <span className={s.typeIcon}>{typeIcon(ct.type)}</span>
              <span>{ct.title}</span>
              <span className={s.typeMeta}>
                {ct.mode} · {ct.available ? ct.stage : `${t("data.planned")}: ${ct.stage}`}
              </span>
            </button>
          ))}
        </div>
      </Modal>
    );
  }
  if (!current) return null;
  return <SourceForm source={source} connector={current} onClose={onClose} onBack={() => setType(null)} />;
}

function SourceForm({
  source,
  connector,
  onClose,
  onBack,
}: {
  source: Source | null;
  connector: ConnectorType;
  onClose: () => void;
  onBack: () => void;
}) {
  const { t } = useI18n();
  const toast = useToast();
  const can = useCan();
  const { me } = useAuth();
  const m = useDataMutations();
  const schema = connector.config_schema as ObjectSchema;
  const secretFields = useMemo(() => new Set(connector.secret_fields ?? []), [connector]);
  const [name, setName] = useState(source?.name ?? connector.title);
  const [config, setConfig] = useState<FormValue>(() => {
    if (!source) return defaultsFor(schema);
    const cfg: FormValue = { ...source.config };
    for (const k of secretFields) cfg[k] = "";
    return cfg;
  });
  const hasStoredSecrets = !!source && [...secretFields].some((k) => source.config[k] === "••••••");
  const [projectIds, setProjectIds] = useState<string[] | null>(source?.project_ids ?? null);
  const [limits, setLimits] = useState({
    timeout_s: source?.timeout_s ?? 60,
    row_limit: source?.row_limit ?? 10000,
    max_concurrency: source?.max_concurrency ?? 4,
    cache_ttl_s: source?.cache_ttl_s ?? 900,
  });
  const [test, setTest] = useState<TestOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const canManage = can("connectors:manage");
  const canConfigure = canManage || can("connectors:configure");
  const projects = me?.projects ?? [];

  const cleanConfig = () =>
    Object.fromEntries(Object.entries(config).filter(([k, v]) => !(secretFields.has(k) && (v === "" || v == null))));

  const runTest = async () => {
    setError(null);
    setTest(null);
    try {
      setTest(await m.testConfig.mutateAsync({ type: connector.type, config: cleanConfig(), source_id: source?.id }));
    } catch (e) {
      setError(errorText(e));
    }
  };

  const save = async () => {
    setError(null);
    try {
      if (source) {
        await m.update.mutateAsync({
          id: source.id,
          body: {
            name,
            config: cleanConfig(),
            ...(canManage ? (projectIds ? { project_ids: projectIds } : { all_projects: true }) : {}),
            ...limits,
          },
        });
        toast.success(t("admin.saved"));
        onClose();
      } else {
        const created = await m.create.mutateAsync({
          name,
          type: connector.type,
          config: cleanConfig(),
          project_ids: projectIds,
          ...limits,
        });
        if (connector.type !== "files" || config.path) {
          const res = await m.refresh.mutateAsync(created.id).catch(() => null);
          if (res) toast.success(t("data.catalogRefreshed", { n: res.tables }));
        }
        onClose();
      }
    } catch (e) {
      setError(errorText(e));
    }
  };

  const act = async (fn: () => Promise<unknown>, ok?: string) => {
    setError(null);
    try {
      await fn();
      if (ok) toast.success(ok);
    } catch (e) {
      setError(errorText(e));
    }
  };

  return (
    <Modal
      open
      size="lg"
      title={
        <span className={s.row}>
          {typeIcon(connector.type)} {source ? source.name : connector.title}
        </span>
      }
      onClose={onClose}
      footer={
        <>
          {source && canManage && (
            <Button
              variant="ghost"
              icon={<Trash2 size={16} />}
              onClick={() => {
                if (window.confirm(t("data.deleteSourceConfirm")))
                  void act(() => m.remove.mutateAsync(source.id)).then(onClose);
              }}
            >
              {t("common.delete")}
            </Button>
          )}
          {!source && <Button onClick={onBack}>{t("auth.back")}</Button>}
          <Button onClick={() => void runTest()} loading={m.testConfig.isPending} disabled={!canConfigure}>
            {t("data.testConnection")}
          </Button>
          <Button
            variant="primary"
            onClick={() => void save()}
            loading={m.create.isPending || m.update.isPending || m.refresh.isPending}
            disabled={!canConfigure || !name}
          >
            {source ? t("common.save") : t("common.create")}
          </Button>
        </>
      }
    >
      {error && <ErrorBox>{error}</ErrorBox>}
      {test && (
        <div className={test.ok ? s.testOk : s.testBad} role="status" style={{ marginBottom: 12 }}>
          {test.ok
            ? `✓ ${t("data.connectionOk")}: ${test.server_version} · ${test.latency_ms} ms`
            : `✕ ${test.message}`}
        </div>
      )}
      {source && (
        <div className={s.row} style={{ marginBottom: 16 }}>
          <Button
            size="sm"
            icon={<RefreshCw size={14} />}
            loading={m.refresh.isPending}
            onClick={() =>
              void act(async () => {
                const r = await m.refresh.mutateAsync(source.id);
                toast.success(t("data.catalogRefreshed", { n: r.tables }));
              })
            }
          >
            {t("data.refreshCatalog")}
          </Button>
          {source.type === "files" && !source.config.path && canConfigure && (
            <>
              <input
                ref={fileRef}
                type="file"
                accept=".csv,.tsv,.xlsx,.parquet"
                hidden
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) void act(() => m.upload.mutateAsync({ id: source.id, file }), file.name);
                  e.target.value = "";
                }}
              />
              <Button
                size="sm"
                icon={<Upload size={14} />}
                loading={m.upload.isPending}
                onClick={() => fileRef.current?.click()}
              >
                {t("data.upload")}
              </Button>
            </>
          )}
          {connector.mode === "sync" && source.type === "gsheets" && (
            <Button
              size="sm"
              loading={m.sync.isPending}
              onClick={() => void act(() => m.sync.mutateAsync(source.id), t("data.sync"))}
            >
              {t("data.sync")}
            </Button>
          )}
          {canManage && (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => void act(() => m.purge.mutateAsync(source.id), t("data.purgeCache"))}
            >
              {t("data.purgeCache")}
            </Button>
          )}
          {source.is_demo && <Badge tone="violet">demo</Badge>}
        </div>
      )}
      <Field label={t("common.name")}>
        <Input value={name} onChange={(e) => setName(e.target.value)} disabled={!canConfigure} />
      </Field>
      <div className={s.section}>
        <div className={s.sectionTitle}>{t("data.params")}</div>
        <JsonSchemaForm
          schema={schema}
          value={config}
          onChange={setConfig}
          secretKeptHint={t("data.secretKept")}
          hasStoredSecrets={hasStoredSecrets}
        />
      </div>
      <div className={s.section}>
        <div className={s.sectionTitle}>{t("data.availability")}</div>
        <div className={s.projects}>
          <Checkbox
            label={t("data.allProjects")}
            checked={projectIds === null}
            disabled={!canManage}
            onChange={(e) => setProjectIds(e.target.checked ? null : [])}
          />
          {projectIds !== null &&
            projects.map((p) => (
              <Checkbox
                key={p.id}
                label={p.name}
                checked={projectIds.includes(p.id)}
                disabled={!canManage}
                onChange={(e) =>
                  setProjectIds(e.target.checked ? [...projectIds, p.id] : projectIds.filter((x) => x !== p.id))
                }
              />
            ))}
        </div>
      </div>
      <div className={s.section}>
        <div className={s.sectionTitle}>{t("data.limits")}</div>
        <div className={s.grid4}>
          {(
            [
              ["timeout_s", t("data.timeout")],
              ["row_limit", t("data.rowLimit")],
              ["max_concurrency", t("data.concurrency")],
              ["cache_ttl_s", t("data.cacheTtl")],
            ] as const
          ).map(([k, label]) => (
            <Field key={k} label={label}>
              <Input
                type="number"
                min={k === "cache_ttl_s" ? 0 : 1}
                value={limits[k]}
                disabled={!canConfigure}
                onChange={(e) => setLimits({ ...limits, [k]: Number(e.target.value) })}
              />
            </Field>
          ))}
        </div>
      </div>
    </Modal>
  );
}
