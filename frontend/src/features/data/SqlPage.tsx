import { Download, Play, Save, Square, Trash2 } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { api } from "../../shared/api/client";
import { downloadPost } from "../../shared/api/download";
import type { RunResult } from "../../shared/api/types";
import { useI18n } from "../../shared/i18n";
import { formatDateTime, formatNumber } from "../../shared/lib/format";
import { storage } from "../../shared/lib/storage";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorBox,
  Field,
  IconButton,
  Input,
  Kbd,
  Modal,
  ResultTable,
  SqlEditor,
  Table,
  Tabs,
  useToast,
  type SqlSchema,
} from "../../shared/ui";
import { useProject } from "../projects/ProjectProvider";
import { SourceSelect } from "./SourceSelect";
import { useSelectedSource } from "./useSelectedSource";
import { useCatalog, useDataMutations, useHistory, useSavedQueries } from "./api";
import s from "./data.module.css";

type Pane = "results" | "history" | "saved";

function newQueryId(): string {
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) => b.toString(16).padStart(2, "0")).join("");
}

export function SqlPage() {
  const { t, locale } = useI18n();
  const toast = useToast();
  const { project } = useProject();
  const { source } = useSelectedSource();
  const catalog = useCatalog(source?.id);
  const history = useHistory();
  const saved = useSavedQueries(project?.id);
  const m = useDataMutations();
  const [sql, setSql] = useState(
    () => storage.get("sql:draft") ?? "SELECT *\nFROM mart_portfolio\nORDER BY event_date DESC\nLIMIT 100",
  );
  const [result, setResult] = useState<RunResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pane, setPane] = useState<Pane>("results");
  const [saving, setSaving] = useState(false);
  const running = useRef<string | null>(null);

  const schema = useMemo<SqlSchema>(() => {
    const out: SqlSchema = {};
    for (const tbl of catalog.data ?? []) out[tbl.name] = tbl.columns.map((c) => c.name);
    return out;
  }, [catalog.data]);

  const body = () => ({ source_id: source!.id, project_id: project?.id ?? null, sql });

  const run = async () => {
    if (!source || m.run.isPending) return;
    storage.set("sql:draft", sql);
    setError(null);
    setPane("results");
    const qid = newQueryId();
    running.current = qid;
    try {
      setResult(await m.run.mutateAsync({ ...body(), query_id: qid }));
    } catch (e) {
      setResult(null);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      running.current = null;
    }
  };

  const cancel = () => {
    if (running.current)
      void api.POST("/api/v1/query/{query_id}/cancel", { params: { path: { query_id: running.current } } });
  };

  const exportAs = (format: "csv" | "xlsx") =>
    downloadPost("/query/export", { ...body(), format }, `result.${format}`).catch((e: Error) =>
      toast.error(e.message),
    );

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <Card padded={false}>
        <div className={s.row} style={{ padding: "12px 16px", borderBottom: "1px solid var(--line-soft)" }}>
          <SourceSelect />
          {source && <Badge mono>{source.dialect}</Badge>}
          <span style={{ flex: 1 }} />
          <span className="muted" style={{ fontSize: 12 }}>
            <Kbd>Ctrl</Kbd> + <Kbd>Enter</Kbd>
          </span>
          <Button icon={<Save size={16} />} onClick={() => setSaving(true)} disabled={!source}>
            {t("data.save")}
          </Button>
          {m.run.isPending ? (
            <Button variant="danger" icon={<Square size={14} />} onClick={cancel}>
              {t("data.cancelQuery")}
            </Button>
          ) : (
            <Button variant="primary" icon={<Play size={16} />} onClick={() => void run()} disabled={!source}>
              {t("data.run")}
            </Button>
          )}
        </div>
        <div style={{ padding: 12 }}>
          <SqlEditor
            value={sql}
            onChange={setSql}
            onRun={() => void run()}
            schema={schema}
            dialect={source?.dialect}
            minHeight={240}
          />
        </div>
      </Card>

      <Card padded={false}>
        <div className={s.row} style={{ padding: "0 16px", borderBottom: "1px solid var(--line-soft)" }}>
          <Tabs<Pane>
            value={pane}
            onChange={setPane}
            items={[
              { key: "results", label: t("data.results") },
              { key: "history", label: t("data.history") },
              { key: "saved", label: t("data.saved"), count: saved.data?.length },
            ]}
            className=""
          />
          <span style={{ flex: 1 }} />
          {pane === "results" && result && (
            <>
              <span className="muted" style={{ fontSize: 13 }}>
                {t("data.rowsShown", {
                  n: formatNumber(result.row_count, locale),
                  ms: formatNumber(result.elapsed_ms, locale),
                })}
              </span>
              {result.truncated && <Badge tone="warn">{t("data.truncated")}</Badge>}
              {result.cached && <Badge tone="info">{t("data.fromCache")}</Badge>}
              <Button size="sm" icon={<Download size={14} />} onClick={() => void exportAs("csv")}>
                {t("data.exportCsv")}
              </Button>
              <Button size="sm" icon={<Download size={14} />} onClick={() => void exportAs("xlsx")}>
                {t("data.exportXlsx")}
              </Button>
            </>
          )}
        </div>
        <div style={{ padding: 16 }}>
          {pane === "results" && (
            <>
              {error && <ErrorBox>{error}</ErrorBox>}
              {result && (
                <>
                  {(result.masked_columns.length > 0 || result.filtered_columns.length > 0) && (
                    <div className={s.row} style={{ marginBottom: 10 }}>
                      {result.masked_columns.length > 0 && (
                        <Badge tone="violet">{t("data.masked", { cols: result.masked_columns.join(", ") })}</Badge>
                      )}
                      {result.filtered_columns.length > 0 && (
                        <Badge tone="info">{t("data.filtered", { cols: result.filtered_columns.join(", ") })}</Badge>
                      )}
                    </div>
                  )}
                  {result.row_count === 0 ? (
                    <EmptyState title={t("data.emptyResult")} />
                  ) : (
                    <ResultTable columns={result.columns} rows={result.rows} locale={locale} />
                  )}
                  <details style={{ marginTop: 12 }}>
                    <summary className="muted" style={{ cursor: "pointer", fontSize: 13 }}>
                      {t("data.executedSql")}
                    </summary>
                    <pre style={{ whiteSpace: "pre-wrap", fontSize: 12 }}>{result.executed_sql}</pre>
                  </details>
                </>
              )}
              {!result && !error && <EmptyState title={t("data.runHint")} />}
            </>
          )}
          {pane === "history" && (
            <Table compact clickable maxHeight={420}>
              <tbody>
                {history.data?.map((h) => (
                  <tr key={h.id} onClick={() => setSql(h.sql)}>
                    <td style={{ whiteSpace: "nowrap" }} className="muted">
                      {formatDateTime(h.created_at, locale)}
                    </td>
                    <td>
                      <Badge tone={h.status === "ok" ? "pos" : "neg"}>{h.status}</Badge>
                    </td>
                    <td>
                      <code style={{ fontSize: 12 }}>{h.sql.slice(0, 160)}</code>
                    </td>
                    <td className="muted">{h.row_count ?? ""}</td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
          {pane === "saved" && (
            <Table compact clickable maxHeight={420}>
              <tbody>
                {saved.data?.map((q) => (
                  <tr key={q.id} onClick={() => setSql(q.sql)}>
                    <td>
                      <strong>{q.name}</strong>
                      <div className="muted" style={{ fontSize: 12 }}>
                        {q.description}
                      </div>
                    </td>
                    <td>
                      <code style={{ fontSize: 12 }}>{q.sql.slice(0, 120)}</code>
                    </td>
                    <td style={{ width: 40 }}>
                      <IconButton
                        label={t("common.delete")}
                        size="sm"
                        onClick={(e) => {
                          e.stopPropagation();
                          m.deleteSaved.mutate(q.id, { onError: (err) => toast.error(err.message) });
                        }}
                      >
                        <Trash2 size={14} />
                      </IconButton>
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </div>
      </Card>
      {saving && source && (
        <SaveDialog
          onClose={() => setSaving(false)}
          onSave={async (name, description) => {
            await m.saveQuery.mutateAsync({
              name,
              description,
              sql,
              source_id: source.id,
              project_id: project?.id ?? null,
            });
            toast.success(t("admin.saved"));
            setSaving(false);
            setPane("saved");
          }}
        />
      )}
    </div>
  );
}

function SaveDialog({
  onClose,
  onSave,
}: {
  onClose: () => void;
  onSave: (name: string, description: string) => Promise<void>;
}) {
  const { t } = useI18n();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);
  return (
    <Modal
      open
      size="sm"
      title={t("data.save")}
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>{t("common.cancel")}</Button>
          <Button
            variant="primary"
            disabled={!name}
            onClick={() => onSave(name, description).catch((e: Error) => setError(e.message))}
          >
            {t("common.save")}
          </Button>
        </>
      }
    >
      {error && <ErrorBox>{error}</ErrorBox>}
      <div style={{ display: "grid", gap: 12 }}>
        <Field label={t("data.queryName")}>
          <Input value={name} onChange={(e) => setName(e.target.value)} autoFocus />
        </Field>
        <Field label={t("common.description")}>
          <Input value={description} onChange={(e) => setDescription(e.target.value)} />
        </Field>
      </div>
    </Modal>
  );
}
