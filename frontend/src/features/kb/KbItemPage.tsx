import { ArrowLeft, History, Link2, Paperclip, Pencil, Send } from "lucide-react";
import { useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { PageBody } from "../../layout/AppShell";
import { API_BASE } from "../../shared/api/client";
import { useI18n, type TKey } from "../../shared/i18n";
import { formatDate, formatDateTime } from "../../shared/lib/format";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorBox,
  Markdown,
  Modal,
  PageSpinner,
  Textarea,
  useToast,
} from "../../shared/ui";
import { useProject } from "../projects/ProjectProvider";
import { useKbItem, useKbMutations, useKbVersions } from "./api";
import { DECISION_TONE, TYPE_TONE } from "./kbStyle";
import { linkHref } from "./links";
import s from "./kb.module.css";

export function KbItemPage() {
  const { id } = useParams();
  const { t, locale } = useI18n();
  const toast = useToast();
  const navigate = useNavigate();
  const { projects } = useProject();
  const item = useKbItem(id);
  const m = useKbMutations();
  const [comment, setComment] = useState("");
  const [history, setHistory] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  if (item.isPending) return <PageSpinner />;
  if (!item.data)
    return (
      <PageBody>
        <Card>
          <EmptyState title={item.error?.message ?? t("common.notFound")} />
        </Card>
      </PageBody>
    );
  const it = item.data;
  const project = it.project_id ? projects.find((p) => p.id === it.project_id)?.name : t("kb.orgWide");

  return (
    <PageBody>
      <Link
        to="/kb"
        className="muted"
        style={{ display: "inline-flex", gap: 6, alignItems: "center", marginBottom: 12 }}
      >
        <ArrowLeft size={16} /> {t("kb.title")}
      </Link>
      <div className={s.detail}>
        <Card>
          <div className={s.cardHead} style={{ marginBottom: 10 }}>
            <Badge tone={TYPE_TONE[it.type]}>{t(`kb.types.${it.type}` as TKey)}</Badge>
            {it.decision && (
              <Badge tone={DECISION_TONE[it.decision] ?? "neutral"} dot>
                {t(`kb.decisions.${it.decision}` as TKey)}
              </Badge>
            )}
            {it.status !== "published" && <Badge>{t(`kb.status.${it.status}` as TKey)}</Badge>}
            <span style={{ flex: 1 }} />
            <Button size="sm" variant="ghost" icon={<History size={14} />} onClick={() => setHistory(true)}>
              {t("kb.version", { n: it.version })}
            </Button>
            {it.can_edit && (
              <Button size="sm" icon={<Pencil size={14} />} onClick={() => navigate(`/kb/${it.id}/edit`)}>
                {t("common.edit")}
              </Button>
            )}
          </div>
          <h1 style={{ fontSize: 26, fontWeight: 800, marginBottom: 8 }}>{it.title}</h1>
          <div className={s.meta}>
            <span>{project}</span>
            <span>{it.author_name}</span>
            <span>{formatDate(it.created_at, locale)}</span>
            {it.tags.map((tg) => (
              <Link key={tg} to={`/kb?tag=${encodeURIComponent(tg)}`}>
                #{tg}
              </Link>
            ))}
          </div>
          {it.summary && <div className={s.lead}>{it.summary}</div>}
          <Markdown>{it.body}</Markdown>
        </Card>
        <div className={s.side}>
          {it.links.length > 0 && (
            <Card title={t("kb.links")}>
              <div className={s.linkList}>
                {it.links.map((l, i) => {
                  const link = l as { kind: string; ref: string; title?: string };
                  const href = linkHref(link.kind, link.ref);
                  return (
                    <span key={i} style={{ display: "flex", gap: 8, alignItems: "center" }}>
                      <Link2 size={14} />
                      <Badge>{t(`kb.linkKinds.${link.kind}` as TKey)}</Badge>
                      {href.startsWith("http") ? (
                        <a href={href} target="_blank" rel="noreferrer noopener">
                          {link.title || link.ref}
                        </a>
                      ) : (
                        <Link to={href}>{link.title || link.ref}</Link>
                      )}
                    </span>
                  );
                })}
              </div>
            </Card>
          )}
          <Card
            title={t("kb.attachments")}
            actions={
              it.can_edit && (
                <>
                  <input
                    ref={fileRef}
                    type="file"
                    hidden
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      if (file) m.attach.mutate({ id: it.id, file }, { onError: (err) => toast.error(err.message) });
                      e.target.value = "";
                    }}
                  />
                  <Button
                    size="sm"
                    icon={<Paperclip size={14} />}
                    onClick={() => fileRef.current?.click()}
                    loading={m.attach.isPending}
                  >
                    {t("kb.attach")}
                  </Button>
                </>
              )
            }
          >
            {it.attachments.length === 0 ? (
              <span className="muted">—</span>
            ) : (
              <div className={s.linkList}>
                {it.attachments.map((a) => (
                  <AttachmentLink
                    key={a.id}
                    href={`${API_BASE}/kb/${it.id}/attachments/${a.id}`}
                    name={a.filename}
                    size={a.size}
                  />
                ))}
              </div>
            )}
          </Card>
          <Card title={t("kb.comments")}>
            {it.comments.map((c) => (
              <div key={c.id} className={s.comment}>
                <div className={s.commentMeta}>
                  {c.author_name} · {formatDateTime(c.created_at, locale)}
                </div>
                {c.text}
              </div>
            ))}
            <div style={{ display: "grid", gap: 8, marginTop: 12 }}>
              <Textarea
                placeholder={t("kb.addComment")}
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                style={{ minHeight: 60 }}
              />
              <Button
                size="sm"
                icon={<Send size={14} />}
                disabled={!comment.trim()}
                loading={m.comment.isPending}
                onClick={() =>
                  m.comment.mutate(
                    { id: it.id, text: comment },
                    { onSuccess: () => setComment(""), onError: (e) => toast.error(e.message) },
                  )
                }
              >
                {t("kb.send")}
              </Button>
            </div>
          </Card>
        </div>
      </div>
      {history && <VersionsDialog id={it.id} onClose={() => setHistory(false)} />}
    </PageBody>
  );
}

function AttachmentLink({ href, name, size }: { href: string; name: string; size: number }) {
  const toast = useToast();
  const open = async () => {
    const { authFetch } = await import("../../shared/api/client");
    const res = await authFetch(new Request(href));
    if (!res.ok) return toast.error(`HTTP ${res.status}`);
    const url = URL.createObjectURL(await res.blob());
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    a.click();
    URL.revokeObjectURL(url);
  };
  return (
    <button
      type="button"
      onClick={() => void open()}
      style={{ all: "unset", cursor: "pointer", color: "var(--brand)" }}
    >
      <Paperclip size={13} /> {name} <span className="muted">({Math.ceil(size / 1024)} KB)</span>
    </button>
  );
}

function VersionsDialog({ id, onClose }: { id: string; onClose: () => void }) {
  const { t, locale } = useI18n();
  const versions = useKbVersions(id, true);
  const [selected, setSelected] = useState(0);
  const v = versions.data?.[selected];
  return (
    <Modal open size="xl" title={t("kb.versions")} onClose={onClose}>
      {versions.error && <ErrorBox>{versions.error.message}</ErrorBox>}
      <div style={{ display: "grid", gridTemplateColumns: "220px 1fr", gap: 20 }}>
        <div style={{ display: "grid", gap: 4, alignContent: "start" }}>
          {versions.data?.map((x, i) => (
            <Button key={x.version} variant={i === selected ? "subtle" : "ghost"} onClick={() => setSelected(i)}>
              {t("kb.version", { n: x.version })} · {formatDate(x.created_at, locale)}
            </Button>
          ))}
        </div>
        {v && (
          <div>
            <div className="muted" style={{ marginBottom: 8 }}>
              {v.author}
            </div>
            <h2 style={{ marginBottom: 8 }}>{v.title}</h2>
            <p className="muted" style={{ marginBottom: 12 }}>
              {v.summary}
            </p>
            <Markdown>{v.body}</Markdown>
          </div>
        )}
      </div>
    </Modal>
  );
}
