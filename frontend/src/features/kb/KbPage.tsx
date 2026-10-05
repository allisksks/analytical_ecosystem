import { BookOpen, Plus, Search } from "lucide-react";
import { useDeferredValue, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { PageBody } from "../../layout/AppShell";
import { useI18n, type TKey } from "../../shared/i18n";
import { formatDate } from "../../shared/lib/format";
import { Badge, Button, Card, EmptyState, Input, PageHeader, PageSpinner, Select, Tabs } from "../../shared/ui";
import { useCan } from "../auth/AuthProvider";
import { useProject } from "../projects/ProjectProvider";
import { useKbSearch } from "./api";
import { DECISION_TONE, KB_TYPES, TYPE_TONE } from "./kbStyle";
import s from "./kb.module.css";

export function KbPage() {
  const { t, locale } = useI18n();
  const can = useCan();
  const navigate = useNavigate();
  const { projects } = useProject();
  const [params, setParams] = useSearchParams();
  const [q, setQ] = useState(params.get("q") ?? "");
  const deferred = useDeferredValue(q);
  const type = params.get("type") ?? "";
  const tags = params.getAll("tag");
  const [sort, setSort] = useState<"relevance" | "newest">("relevance");
  const res = useKbSearch({
    q: deferred,
    type: type || undefined,
    tag: tags.length ? tags : undefined,
    sort: deferred ? sort : "newest",
  });
  const projectName = (id?: string | null) => (id ? (projects.find((p) => p.id === id)?.name ?? "—") : t("kb.orgWide"));
  const setParam = (fn: (p: URLSearchParams) => void) =>
    setParams((p) => {
      fn(p);
      return p;
    });

  return (
    <PageBody>
      <PageHeader
        crumbs={[t("kb.title")]}
        title={t("kb.subtitle")}
        actions={
          can("kb:write") && (
            <Button variant="primary" icon={<Plus size={16} />} onClick={() => navigate("/kb/new")}>
              {t("kb.newItem")}
            </Button>
          )
        }
      />
      <div className={s.toolbar}>
        <div className={s.searchBox}>
          <Search size={18} />
          <Input
            type="search"
            placeholder={t("kb.search")}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            aria-label={t("common.search")}
          />
        </div>
        <Select
          value={sort}
          onChange={(e) => setSort(e.target.value as typeof sort)}
          disabled={!deferred}
          aria-label="sort"
        >
          <option value="relevance">{t("kb.sortRelevance")}</option>
          <option value="newest">{t("kb.sortNewest")}</option>
        </Select>
      </div>
      <Tabs
        variant="pills"
        value={type || "all"}
        onChange={(k) => setParam((p) => (k === "all" ? p.delete("type") : p.set("type", k)))}
        items={[
          { key: "all", label: t("kb.all") },
          ...KB_TYPES.map((k) => ({
            key: k,
            label: t(`kb.types.${k}` as TKey),
            count: res.data?.facets.types[k] ?? 0,
          })),
        ]}
      />
      <div className={s.tags}>
        <span className="muted" style={{ fontSize: 12, fontWeight: 800 }}>
          {t("kb.tags").toUpperCase()}:
        </span>
        {res.data?.facets.tags.map((tg) => {
          const active = tags.includes(tg.tag);
          return (
            <button
              key={tg.tag}
              type="button"
              className={`${s.tag} ${active ? s.tagActive : ""}`}
              aria-pressed={active}
              onClick={() =>
                setParam((p) => {
                  p.delete("tag");
                  for (const x of active ? tags.filter((v) => v !== tg.tag) : [...tags, tg.tag]) p.append("tag", x);
                })
              }
            >
              #{tg.tag} <span className="muted">{tg.count}</span>
            </button>
          );
        })}
      </div>
      {res.isPending ? (
        <PageSpinner />
      ) : !res.data?.items.length ? (
        <Card>
          <EmptyState icon={<BookOpen size={26} />} title={t("kb.nothing")} description={t("kb.nothingHint")} />
        </Card>
      ) : (
        <>
          <p className="muted" style={{ marginBottom: 12, fontSize: 13 }}>
            {t("kb.found", { n: res.data.total })}
          </p>
          <div className={s.cards}>
            {res.data.items.map((it) => (
              <Link key={it.id} to={`/kb/${it.id}`} className={s.card}>
                <div className={s.cardHead}>
                  <Badge tone={TYPE_TONE[it.type]}>{t(`kb.types.${it.type}` as TKey)}</Badge>
                  {it.decision && (
                    <Badge tone={DECISION_TONE[it.decision] ?? "neutral"} dot>
                      {t(`kb.decisions.${it.decision}` as TKey)}
                    </Badge>
                  )}
                  {it.status !== "published" && <Badge>{t(`kb.status.${it.status}` as TKey)}</Badge>}
                  <span className={s.date}>{formatDate(it.created_at, locale)}</span>
                </div>
                <div className={s.cardTitle}>{it.title}</div>
                <div className={s.cardSummary}>{it.summary}</div>
                <div className={s.cardFoot}>
                  <span>
                    {projectName(it.project_id)} · {it.author_name}
                  </span>
                  <span>
                    {it.tags
                      .slice(0, 3)
                      .map((x) => `#${x}`)
                      .join(" ")}
                  </span>
                </div>
              </Link>
            ))}
          </div>
        </>
      )}
    </PageBody>
  );
}
