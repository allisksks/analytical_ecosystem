import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { useNavigate, useParams } from "react-router";
import { PageBody } from "../../layout/AppShell";
import type { KbItem, Schemas } from "../../shared/api/types";
import { useI18n, type TKey } from "../../shared/i18n";
import {
  Button,
  Card,
  ErrorBox,
  Field,
  IconButton,
  Input,
  Markdown,
  PageHeader,
  PageSpinner,
  Select,
  Tabs,
  Textarea,
} from "../../shared/ui";
import { useCan } from "../auth/AuthProvider";
import { useProject } from "../projects/ProjectProvider";
import { useKbItem, useKbMutations, useKbTemplates } from "./api";
import { KB_TYPES } from "./kbStyle";
import s from "./kb.module.css";

type KbType = Schemas["ItemIn"]["type"];
type LinkIn = Schemas["LinkIn"];
const LINK_KINDS: LinkIn["kind"][] = ["event", "metric", "dashboard", "experiment", "kb", "url"];

export function KbEditorPage() {
  const { id } = useParams();
  const item = useKbItem(id);
  if (id && item.isPending) return <PageSpinner />;
  return <Editor key={item.data?.id ?? "new"} item={item.data ?? null} />;
}

function Editor({ item }: { item: KbItem | null }) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const can = useCan();
  const { projects, project: current } = useProject();
  const templates = useKbTemplates();
  const m = useKbMutations();
  const [type, setType] = useState<KbType>((item?.type as KbType) ?? "research");
  const [projectId, setProjectId] = useState<string>(item ? (item.project_id ?? "") : (current?.id ?? ""));
  const [title, setTitle] = useState(item?.title ?? "");
  const [summary, setSummary] = useState(item?.summary ?? "");
  const [tags, setTags] = useState((item?.tags ?? []).join(", "));
  const [body, setBody] = useState(item?.body ?? "");
  const [decision, setDecision] = useState(item?.decision ?? "");
  const [links, setLinks] = useState<LinkIn[]>((item?.links as LinkIn[] | undefined) ?? []);
  const [tab, setTab] = useState<"write" | "preview">("write");
  const [error, setError] = useState<string | null>(null);
  const writable = projects.filter((p) => can("kb:write", p.id));

  const changeType = (next: KbType) => {
    const tpl = templates.data?.[next];
    const prevTpl = templates.data?.[type];
    if (tpl && (!body.trim() || body === prevTpl)) setBody(tpl);
    setType(next);
  };
  const save = async (status: "draft" | "published") => {
    setError(null);
    const common = {
      title,
      summary,
      body,
      decision,
      tags: tags
        .split(",")
        .map((x) => x.trim())
        .filter(Boolean),
      links: links.filter((l) => l.ref.trim()),
    };
    try {
      const saved = item
        ? await m.update.mutateAsync({ id: item.id, body: { ...common, type, status } })
        : await m.create.mutateAsync({ ...common, type, status, project_id: projectId || null });
      navigate(`/kb/${saved.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <PageBody>
      <PageHeader
        crumbs={[t("kb.title")]}
        title={item ? item.title : t("kb.newItem")}
        actions={
          <>
            <Button onClick={() => navigate(-1)}>{t("common.cancel")}</Button>
            <Button
              onClick={() => void save("draft")}
              disabled={!title}
              loading={m.create.isPending || m.update.isPending}
            >
              {t("kb.saveDraft")}
            </Button>
            <Button
              variant="primary"
              onClick={() => void save("published")}
              disabled={!title}
              loading={m.create.isPending || m.update.isPending}
            >
              {t("kb.publish")}
            </Button>
          </>
        }
      />
      {error && <ErrorBox>{error}</ErrorBox>}
      <Card>
        <div className={s.editorGrid}>
          <Field label={t("data.type")}>
            <Select value={type} onChange={(e) => changeType(e.target.value as KbType)} aria-label="type">
              {KB_TYPES.map((k) => (
                <option key={k} value={k}>
                  {t(`kb.types.${k}` as TKey)}
                </option>
              ))}
            </Select>
          </Field>
          <Field label={t("common.project")}>
            <Select value={projectId} disabled={!!item} onChange={(e) => setProjectId(e.target.value)}>
              <option value="">{t("kb.orgWide")}</option>
              {writable.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field label={t("kb.decision")}>
            <Select value={decision} onChange={(e) => setDecision(e.target.value)}>
              <option value="">—</option>
              {["accepted", "rejected", "inconclusive"].map((d) => (
                <option key={d} value={d}>
                  {t(`kb.decisions.${d}` as TKey)}
                </option>
              ))}
            </Select>
          </Field>
          <Field label={t("bi.title")} className="full" required>
            <Input value={title} onChange={(e) => setTitle(e.target.value)} />
          </Field>
          <Field label={t("kb.summary")} className="full">
            <Textarea value={summary} onChange={(e) => setSummary(e.target.value)} style={{ minHeight: 60 }} />
          </Field>
          <Field label={t("kb.tags")} hint={t("kb.tagsHint")} className="full">
            <Input value={tags} onChange={(e) => setTags(e.target.value)} />
          </Field>
        </div>
        <div style={{ marginTop: 20 }}>
          <Tabs<"write" | "preview">
            value={tab}
            onChange={setTab}
            items={[
              { key: "write", label: t("kb.write") },
              { key: "preview", label: t("kb.previewTab") },
            ]}
          />
          <div style={{ marginTop: 12 }}>
            {tab === "write" ? (
              <Textarea
                className={s.body}
                value={body}
                onChange={(e) => setBody(e.target.value)}
                aria-label={t("kb.body")}
              />
            ) : (
              <div style={{ minHeight: 360 }}>
                <Markdown>{body}</Markdown>
              </div>
            )}
          </div>
        </div>
        <div style={{ marginTop: 20 }}>
          <Field label={t("kb.links")}>
            <div>
              {links.map((l, i) => (
                <div key={i} className={s.linkRow}>
                  <Select
                    value={l.kind}
                    onChange={(e) =>
                      setLinks(links.map((x, j) => (j === i ? { ...x, kind: e.target.value as LinkIn["kind"] } : x)))
                    }
                  >
                    {LINK_KINDS.map((k) => (
                      <option key={k} value={k}>
                        {t(`kb.linkKinds.${k}` as TKey)}
                      </option>
                    ))}
                  </Select>
                  <Input
                    placeholder={t("kb.ref")}
                    value={l.ref}
                    onChange={(e) => setLinks(links.map((x, j) => (j === i ? { ...x, ref: e.target.value } : x)))}
                  />
                  <Input
                    placeholder={t("bi.title")}
                    value={l.title ?? ""}
                    onChange={(e) => setLinks(links.map((x, j) => (j === i ? { ...x, title: e.target.value } : x)))}
                  />
                  <IconButton label={t("common.delete")} onClick={() => setLinks(links.filter((_, j) => j !== i))}>
                    <Trash2 size={16} />
                  </IconButton>
                </div>
              ))}
              <Button
                size="sm"
                icon={<Plus size={14} />}
                onClick={() => setLinks([...links, { kind: "metric", ref: "", title: "" }])}
              >
                {t("kb.addLink")}
              </Button>
            </div>
          </Field>
        </div>
      </Card>
    </PageBody>
  );
}
