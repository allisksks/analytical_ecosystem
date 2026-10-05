import clsx from "clsx";
import { Check, FileText, Quote, Sparkles, Upload, X } from "lucide-react";
import { useRef, useState } from "react";
import { useSearchParams } from "react-router";
import type { ParamIn } from "../../shared/api/types";
import { useI18n } from "../../shared/i18n";
import { formatDateTime } from "../../shared/lib/format";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorBox,
  Field,
  Input,
  Modal,
  PageSpinner,
  Tabs,
  Textarea,
  useToast,
} from "../../shared/ui";
import { useCan } from "../auth/AuthProvider";
import { ParamsEditor } from "./ParamsEditor";
import { useAiDraft, useAiDraftMutations, useAiDrafts, type TrackingDraftItem } from "./api";
import s from "./ems.module.css";

const ACCEPT = ".docx,.pdf,.md,.markdown,.txt";

export function AiDraftDialog({
  projectId,
  onCreated,
  onClose,
}: {
  projectId: string;
  onCreated: (id: string) => void;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const toast = useToast();
  const m = useAiDraftMutations();
  const input = useRef<HTMLInputElement>(null);
  const [mode, setMode] = useState<"file" | "text">("file");
  const [file, setFile] = useState<File | null>(null);
  const [text, setText] = useState("");
  const [appVersion, setAppVersion] = useState("");
  const [drag, setDrag] = useState(false);
  const ready = mode === "file" ? !!file : text.trim().length > 20;
  const submit = () =>
    m.create.mutate(
      { projectId, file: mode === "file" ? file : null, text: mode === "text" ? text : "", appVersion },
      { onSuccess: (d) => onCreated(d.id), onError: (e) => toast.error(e.message) },
    );
  return (
    <Modal
      open
      size="lg"
      title={t("ems.ai.title")}
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>{t("common.cancel")}</Button>
          <Button
            variant="primary"
            icon={<Sparkles size={16} />}
            disabled={!ready}
            loading={m.create.isPending}
            onClick={submit}
          >
            {m.create.isPending ? t("ems.ai.reading") : t("ems.ai.generate")}
          </Button>
        </>
      }
    >
      <div className={s.aiDialog}>
        <p className="muted">{t("ems.ai.hint")}</p>
        <Tabs<"file" | "text">
          variant="pills"
          value={mode}
          onChange={setMode}
          items={[
            { key: "file", label: t("ems.ai.fromFile") },
            { key: "text", label: t("ems.ai.fromText") },
          ]}
        />
        {mode === "file" ? (
          <button
            type="button"
            className={clsx(s.dropZone, drag && s.dropZoneActive)}
            onClick={() => input.current?.click()}
            onDragOver={(e) => {
              e.preventDefault();
              setDrag(true);
            }}
            onDragLeave={() => setDrag(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDrag(false);
              setFile(e.dataTransfer.files[0] ?? null);
            }}
          >
            {file ? <FileText size={28} /> : <Upload size={28} />}
            <strong>{file ? file.name : t("ems.ai.drop")}</strong>
            <span className="muted">{t("ems.ai.formats")}</span>
            <input
              ref={input}
              type="file"
              accept={ACCEPT}
              hidden
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </button>
        ) : (
          <Textarea
            rows={10}
            aria-label={t("ems.ai.fromText")}
            placeholder={t("ems.ai.textPlaceholder")}
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
        )}
        <Field label={t("ems.appVersion")} hint={t("ems.ai.versionHint")}>
          <Input mono placeholder="1.9.0" value={appVersion} onChange={(e) => setAppVersion(e.target.value)} />
        </Field>
      </div>
    </Modal>
  );
}

export function AiDraftsTab({ projectId, onNew }: { projectId: string; onNew: () => void }) {
  const { t, locale } = useI18n();
  const [params, setParams] = useSearchParams();
  const drafts = useAiDrafts(projectId);
  const selectedId = params.get("draft") ?? drafts.data?.[0]?.id;
  if (drafts.isPending) return <PageSpinner />;
  if (!drafts.data?.length)
    return (
      <Card>
        <EmptyState
          icon={<Sparkles size={28} />}
          title={t("ems.ai.emptyTitle")}
          description={t("ems.ai.emptyText")}
          action={
            <Button variant="primary" icon={<Sparkles size={16} />} onClick={onNew}>
              {t("ems.ai.title")}
            </Button>
          }
        />
      </Card>
    );
  return (
    <div className={s.layout}>
      <Card padded={false}>
        <ul className={s.draftList}>
          {drafts.data.map((d) => (
            <li key={d.id}>
              <button
                type="button"
                className={clsx(s.draftRow, d.id === selectedId && s.draftRowActive)}
                onClick={() => setParams({ tab: "aiDrafts", draft: d.id })}
              >
                <span className={s.draftTitle}>{d.title}</span>
                <span className={s.chips}>
                  {d.app_version && <Badge mono>v{d.app_version}</Badge>}
                  {d.pending > 0 && <Badge tone="warn">{t("ems.ai.pendingN", { n: d.pending })}</Badge>}
                  {d.accepted > 0 && <Badge tone="pos">{t("ems.ai.acceptedN", { n: d.accepted })}</Badge>}
                </span>
                <span className="muted" style={{ fontSize: 12 }}>
                  {d.created_by} · {formatDateTime(d.created_at, locale)}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </Card>
      {selectedId && <DraftDetail id={selectedId} />}
    </div>
  );
}

function DraftDetail({ id }: { id: string }) {
  const { t } = useI18n();
  const draft = useAiDraft(id);
  const [showSource, setShowSource] = useState(false);
  if (!draft.data) return <PageSpinner />;
  const d = draft.data;
  return (
    <div className={s.draftDetail}>
      <Card
        title={d.title}
        subtitle={`${t("ems.ai.model")}: ${d.model}`}
        actions={
          <Button size="sm" variant="ghost" icon={<FileText size={14} />} onClick={() => setShowSource((v) => !v)}>
            {showSource ? t("ems.ai.hideSource") : t("ems.ai.showSource")}
          </Button>
        }
      >
        <p>{d.summary || "—"}</p>
        <p className="muted" style={{ fontSize: 12, marginTop: 8 }}>
          {t("ems.ai.flow")}
        </p>
        {d.truncated && <ErrorBox>{t("ems.ai.truncated")}</ErrorBox>}
        {showSource && <pre className={s.sourceText}>{d.source_text}</pre>}
      </Card>
      {d.items.length === 0 ? (
        <Card>
          <EmptyState title={t("ems.ai.noItems")} />
        </Card>
      ) : (
        d.items.map((it) => <ItemCard key={it.id} draftId={d.id} projectId={d.project_id} item={it} />)
      )}
    </div>
  );
}

function ItemCard({ draftId, projectId, item }: { draftId: string; projectId: string; item: TrackingDraftItem }) {
  const { t } = useI18n();
  const toast = useToast();
  const can = useCan();
  const [, setParams] = useSearchParams();
  const m = useAiDraftMutations();
  const [name, setName] = useState(item.name);
  const [description, setDescription] = useState(item.description);
  const [params, setParamsState] = useState<ParamIn[]>(item.params);
  const pending = item.status === "pending";
  const editable = pending && can("events:edit", projectId);
  const dirty =
    name !== item.name || description !== item.description || JSON.stringify(params) !== JSON.stringify(item.params);
  const added = new Set(
    (item.diff?.changes as { name: string; kind: string }[] | undefined)
      ?.filter((c) => c.kind !== "removed")
      .map((c) => c.name),
  );
  const fail = (e: Error) => toast.error(e.message);
  const save = () =>
    m.patch.mutateAsync({
      draftId,
      itemId: item.id,
      body: { ...(item.action === "create" ? { name } : {}), description, params },
    });
  const decide = async (decision: "accept" | "reject") => {
    try {
      if (dirty && decision === "accept") await save();
      await m.decide.mutateAsync({ draftId, itemId: item.id, decision });
    } catch (e) {
      fail(e as Error);
    }
  };
  return (
    <Card className={clsx(s.itemCard, !pending && s.itemDone)}>
      <div className={s.itemHead}>
        <Badge tone={item.action === "create" ? "info" : "warn"}>
          {item.action === "create" ? t("ems.ai.new") : t("ems.ai.change")}
        </Badge>
        {editable && item.action === "create" ? (
          <Input
            mono
            aria-label={t("ems.name")}
            value={name}
            onChange={(e) => setName(e.target.value)}
            style={{ maxWidth: 320 }}
          />
        ) : (
          <span className={s.eventName}>{item.name}</span>
        )}
        {item.action === "update" && item.diff && <Badge mono>{item.diff.bump as string}</Badge>}
        <span style={{ flex: 1 }} />
        {item.status === "accepted" && (
          <Badge tone="pos" dot>
            {t("ems.ai.acceptedAs", { v: item.result_version })}
          </Badge>
        )}
        {item.status === "rejected" && <Badge>{t("ems.ai.rejected")}</Badge>}
      </div>
      {editable ? (
        <Textarea
          rows={2}
          aria-label={t("common.description")}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      ) : (
        <p>{item.description}</p>
      )}
      {(item.goal || item.question) && (
        <dl className={s.gqm}>
          {item.goal && (
            <>
              <dt>{t("ems.goal")}</dt>
              <dd>{item.goal}</dd>
            </>
          )}
          {item.question && (
            <>
              <dt>{t("ems.question")}</dt>
              <dd>{item.question}</dd>
            </>
          )}
        </dl>
      )}
      {item.quote && (
        <blockquote className={s.quote}>
          <Quote size={14} aria-hidden />
          <span>{item.quote}</span>
        </blockquote>
      )}
      {item.rationale && <p className="muted">{item.rationale}</p>}
      {item.warnings.map((w) => (
        <div key={w} className={s.warning}>
          {w}
        </div>
      ))}
      <div className={s.sectionTitle}>{t("ems.ownParams")}</div>
      {editable ? (
        <ParamsEditor value={params} onChange={setParamsState} />
      ) : (
        <div className={s.chips}>
          {item.params.map((p) => (
            <Badge key={p.name} mono tone={added.has(p.name) ? "pos" : "neutral"}>
              {p.name}: {p.type}
            </Badge>
          ))}
        </div>
      )}
      {item.action === "update" && editable && added.size > 0 && (
        <div className="muted" style={{ fontSize: 12 }}>
          {t("ems.ai.addedParams", { list: [...added].join(", ") })}
        </div>
      )}
      <div className={s.itemActions}>
        {editable && (
          <>
            <Button
              variant="primary"
              icon={<Check size={16} />}
              loading={m.decide.isPending || m.patch.isPending}
              onClick={() => void decide("accept")}
            >
              {item.action === "create" ? t("ems.ai.accept") : t("ems.ai.acceptChange")}
            </Button>
            {dirty && (
              <Button onClick={() => void save().catch(fail)} loading={m.patch.isPending}>
                {t("common.save")}
              </Button>
            )}
            <Button variant="ghost" icon={<X size={16} />} onClick={() => void decide("reject")}>
              {t("ems.ai.reject")}
            </Button>
          </>
        )}
        {item.status === "accepted" && (
          <Button size="sm" onClick={() => setParams({ tab: "registry", event: item.name })}>
            {t("ems.ai.openEvent")}
          </Button>
        )}
      </div>
    </Card>
  );
}
