import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import {
  ArrowRight,
  BarChart3,
  BookOpen,
  CornerDownLeft,
  FileText,
  FlaskConical,
  Plus,
  Search,
  Sigma,
  Sparkles,
  Zap,
} from "lucide-react";
import { useDeferredValue, useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import { useNavigate } from "react-router";
import type { SideGroup } from "../../layout/Sidebar";
import { useShell } from "../../layout/shell";
import { api } from "../../shared/api/client";
import { useI18n, type TKey } from "../../shared/i18n";
import { Kbd } from "../../shared/ui";
import { useExperiments } from "../ab/api";
import { useAiStatus } from "../ai/api";
import { useCan } from "../auth/AuthProvider";
import { useDashboards, useMetrics } from "../bi/api";
import { useEvents } from "../ems/api";
import { useProject } from "../projects/ProjectProvider";
import { rank, type Command } from "./search";
import s from "./CommandPalette.module.css";

const GROUP_ICON: Record<Command["group"], ReactNode> = {
  pages: <ArrowRight size={16} />,
  actions: <Plus size={16} />,
  events: <Zap size={16} />,
  experiments: <FlaskConical size={16} />,
  dashboards: <BarChart3 size={16} />,
  metrics: <Sigma size={16} />,
  kb: <BookOpen size={16} />,
  ask: <Sparkles size={16} />,
};

export function CommandPalette({ nav }: { nav: SideGroup[] }) {
  const { paletteOpen } = useShell();
  return paletteOpen ? <Palette nav={nav} /> : null;
}

function Palette({ nav }: { nav: SideGroup[] }) {
  const { t } = useI18n();
  const can = useCan();
  const navigate = useNavigate();
  const { setPaletteOpen, openAssistant } = useShell();
  const { project } = useProject();
  const pid = project?.id;
  const [query, setQuery] = useState("");
  const q = useDeferredValue(query);
  const [active, setActive] = useState(0);
  const listId = useId();
  const input = useRef<HTMLInputElement>(null);
  const close = () => setPaletteOpen(false);

  const ai = useAiStatus();
  const events = useEvents(can("events:view", pid) ? pid : undefined);
  const experiments = useExperiments(can("experiments:view", pid) || can("experiments:results", pid) ? pid : undefined);
  const dashboards = useDashboards(pid ?? null);
  const metrics = useMetrics();
  const kb = useQuery({
    queryKey: ["palette", "kb", q],
    queryFn: async () => (await api.GET("/api/v1/kb", { params: { query: { q, limit: 6, sort: "relevance" } } })).data!,
    enabled: q.trim().length >= 2 && can("kb:view"),
    staleTime: 30_000,
  });

  const commands = useMemo<Command[]>(() => {
    const list: Command[] = nav.flatMap((g) =>
      g.items.map((it) => ({
        id: `page:${it.to}`,
        group: "pages" as const,
        label: t(it.label),
        hint: g.label ? t(g.label) : undefined,
        to: it.to,
      })),
    );
    const action = (ok: boolean, id: string, label: TKey, to: string, keywords = "") =>
      ok && list.push({ id, group: "actions", label: t(label), to, keywords });
    action(can("events:edit", pid), "new-event", "palette.newEvent", "/ems?new=event", "event событие");
    action(
      can("events:edit", pid) && !!ai.data?.enabled,
      "ai-drafts",
      "palette.aiDrafts",
      "/ems?tab=aiDrafts&new=ai",
      "ии документ разметка",
    );
    action(
      can("experiments:propose", pid) || can("experiments:edit", pid),
      "new-exp",
      "palette.newExperiment",
      "/ab/new",
      "ab тест эксперимент",
    );
    action(can("kb:write"), "new-kb", "palette.newKb", "/kb/new", "запись знание");
    action(can("sql:run", pid) || can("sql:run_all"), "sql", "palette.sql", "/data/sql", "sql запрос");
    for (const e of events.data ?? [])
      list.push({ id: `ev:${e.id}`, group: "events", label: e.name, hint: e.description, to: `/ems?event=${e.name}` });
    for (const x of experiments.data ?? [])
      list.push({ id: `ab:${x.id}`, group: "experiments", label: x.name, hint: x.key, to: `/ab/${x.id}` });
    for (const d of dashboards.data ?? [])
      list.push({
        id: `bi:${d.id}`,
        group: "dashboards",
        label: d.title,
        hint: d.description,
        to: `/bi/dashboards?d=${d.id}`,
      });
    for (const m of metrics.data ?? [])
      list.push({ id: `m:${m.key}`, group: "metrics", label: m.name, hint: m.key, to: `/data/metrics?key=${m.key}` });
    return list;
  }, [nav, t, can, pid, ai.data, events.data, experiments.data, dashboards.data, metrics.data]);

  const results = useMemo(() => {
    const found = rank(commands, q, q.trim() ? 6 : 12).filter(
      (c) => q.trim() || c.group === "pages" || c.group === "actions",
    );
    for (const k of kb.data?.items ?? [])
      found.push({ id: `kb:${k.id}`, group: "kb", label: k.title, hint: k.summary, to: `/kb/${k.id}` });
    if (q.trim() && ai.data?.enabled && can("kb:ask"))
      found.push({
        id: "ask",
        group: "ask",
        label: t("palette.ask", { q: q.trim() }),
        run: () => openAssistant(q.trim()),
      });
    return found;
  }, [commands, q, kb.data, ai.data, can, t, openAssistant]);

  useEffect(() => input.current?.focus(), []);
  useEffect(() => {
    document.getElementById(`${listId}-${active}`)?.scrollIntoView({ block: "nearest" });
  }, [active, listId]);

  const choose = (c: Command | undefined) => {
    if (!c) return;
    close();
    if (c.run) c.run();
    else if (c.to) navigate(c.to);
  };

  return (
    <div className={s.backdrop} onMouseDown={(e) => e.target === e.currentTarget && close()}>
      <div className={s.palette} role="dialog" aria-modal="true" aria-label={t("shell.search")}>
        <div className={s.inputRow}>
          <Search size={18} aria-hidden />
          <input
            ref={input}
            className={s.input}
            role="combobox"
            aria-expanded="true"
            aria-controls={listId}
            aria-activedescendant={results.length ? `${listId}-${active}` : undefined}
            placeholder={t("palette.placeholder")}
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setActive(0);
            }}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") {
                e.preventDefault();
                setActive((a) => Math.min(a + 1, results.length - 1));
              } else if (e.key === "ArrowUp") {
                e.preventDefault();
                setActive((a) => Math.max(a - 1, 0));
              } else if (e.key === "Enter") {
                e.preventDefault();
                choose(results[active]);
              } else if (e.key === "Escape") {
                close();
              }
            }}
          />
          <Kbd>Esc</Kbd>
        </div>
        <ul id={listId} role="listbox" className={s.list} aria-label={t("shell.search")}>
          {results.length === 0 && <li className={s.empty}>{t("palette.empty")}</li>}
          {results.map((c, i) => {
            const header = i === 0 || results[i - 1].group !== c.group ? c.group : null;
            return (
              <li key={c.id} role="presentation">
                {header && <div className={s.groupLabel}>{t(`palette.groups.${header}` as TKey)}</div>}
                <div
                  id={`${listId}-${i}`}
                  role="option"
                  aria-selected={i === active}
                  className={clsx(s.option, i === active && s.optionActive)}
                  onMouseMove={() => setActive(i)}
                  onClick={() => choose(c)}
                >
                  <span className={s.optionIcon}>
                    {c.group === "kb" ? <FileText size={16} /> : GROUP_ICON[c.group]}
                  </span>
                  <span className={s.optionLabel}>{c.label}</span>
                  {c.hint && <span className={s.optionHint}>{c.hint}</span>}
                  {i === active && <CornerDownLeft size={14} className={s.enter} aria-hidden />}
                </div>
              </li>
            );
          })}
        </ul>
        <div className={s.footer}>
          <span>
            <Kbd>↑</Kbd> <Kbd>↓</Kbd> {t("palette.navigate")}
          </span>
          <span>
            <Kbd>Enter</Kbd> {t("palette.open")}
          </span>
          <span>
            <Kbd>Ctrl</Kbd> <Kbd>J</Kbd> {t("palette.assistant")}
          </span>
        </div>
      </div>
    </div>
  );
}
