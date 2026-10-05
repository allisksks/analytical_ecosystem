import clsx from "clsx";
import {
  AlertTriangle,
  BookOpen,
  CheckCircle2,
  FileText,
  FlaskConical,
  Gavel,
  Search,
  Sparkles,
  TerminalSquare,
  Zap,
} from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link } from "react-router";
import { useAuth, useCan } from "../features/auth/AuthProvider";
import { useAiStatus } from "../features/ai/api";
import { useInbox, type InboxTask } from "../features/inbox/api";
import { useProject } from "../features/projects/ProjectProvider";
import { PageBody } from "../layout/AppShell";
import { useShell } from "../layout/shell";
import { useI18n, type TKey } from "../shared/i18n";
import { formatDateTime } from "../shared/lib/format";
import { Card, EmptyState, Kbd, Skeleton } from "../shared/ui";
import s from "./HomePage.module.css";

const TASK_ICON: Record<InboxTask["kind"], ReactNode> = {
  event_review: <Zap size={18} />,
  ai_drafts: <Sparkles size={18} />,
  alert: <AlertTriangle size={18} />,
  experiment_review: <FlaskConical size={18} />,
  experiment_decision: <Gavel size={18} />,
  experiment_ready: <FlaskConical size={18} />,
};

function greeting(hour: number): TKey {
  if (hour < 6) return "home.night";
  if (hour < 12) return "home.morning";
  if (hour < 18) return "home.day";
  return "home.evening";
}

export function HomePage() {
  const { t, locale } = useI18n();
  const { me } = useAuth();
  const can = useCan();
  const { project } = useProject();
  const { setPaletteOpen, openAssistant } = useShell();
  const ai = useAiStatus();
  const inbox = useInbox(project?.id);
  const pid = project?.id;
  const firstName = me?.user.name.split(/\s+/)[0] ?? "";
  const [hour] = useState(() => new Date().getHours());

  const actions: { to?: string; onClick?: () => void; icon: ReactNode; label: TKey; hint: TKey; show: boolean }[] = [
    {
      to: "/ems?tab=aiDrafts&new=ai",
      icon: <FileText size={20} />,
      label: "home.aDoc",
      hint: "home.aDocHint",
      show: can("events:edit", pid) && !!ai.data?.enabled,
    },
    {
      to: "/ab/new",
      icon: <FlaskConical size={20} />,
      label: "home.aExperiment",
      hint: "home.aExperimentHint",
      show: can("experiments:propose", pid) || can("experiments:edit", pid),
    },
    {
      to: "/data/sql",
      icon: <TerminalSquare size={20} />,
      label: "home.aSql",
      hint: "home.aSqlHint",
      show: can("sql:run", pid) || can("sql:run_all"),
    },
    {
      onClick: () => openAssistant(),
      icon: <Sparkles size={20} />,
      label: "home.aAsk",
      hint: "home.aAskHint",
      show: !!ai.data?.enabled && can("kb:ask"),
    },
    { to: "/kb/new", icon: <BookOpen size={20} />, label: "home.aKb", hint: "home.aKbHint", show: can("kb:write") },
  ];

  return (
    <PageBody>
      <div className={s.wrap}>
        <section className={s.hero}>
          <h1 className={s.title}>
            {t(greeting(hour))}
            {firstName && `, ${firstName}`}
          </h1>
          <p className={s.lead}>{project ? t("home.lead", { project: project.name }) : t("app.tagline")}</p>
          <button type="button" className={s.search} onClick={() => setPaletteOpen(true)}>
            <Search size={18} aria-hidden />
            <span>{t("home.search")}</span>
            <span className={s.kbd}>
              <Kbd>Ctrl</Kbd> <Kbd>K</Kbd>
            </span>
          </button>
        </section>

        <div className={s.columns}>
          <Card
            title={t("home.inbox")}
            subtitle={inbox.data ? t("home.inboxCount", { n: inbox.data.tasks.length }) : undefined}
            padded={false}
          >
            {!project ? (
              <EmptyState title={t("projects.none")} />
            ) : inbox.isPending ? (
              <div style={{ padding: 16 }}>
                <Skeleton height={48} />
              </div>
            ) : !inbox.data?.tasks.length ? (
              <EmptyState
                icon={<CheckCircle2 size={28} />}
                title={t("home.allDone")}
                description={t("home.allDoneHint")}
              />
            ) : (
              <ul className={s.tasks}>
                {inbox.data.tasks.map((task, i) => (
                  <li key={`${task.kind}-${task.link}-${i}`}>
                    <Link to={task.link} className={clsx(s.task, s[task.severity ?? "info"])}>
                      <span className={s.taskIcon}>{TASK_ICON[task.kind]}</span>
                      <span className={s.taskText}>
                        <span className={s.taskKind}>
                          {t(`home.kinds.${task.kind}` as TKey, { n: task.subtitle ?? "" })}
                        </span>
                        <span className={s.taskTitle}>{task.title}</span>
                      </span>
                      <span className={s.taskMeta}>
                        {task.kind !== "ai_drafts" && task.kind !== "experiment_ready" && task.subtitle && (
                          <span>{task.subtitle}</span>
                        )}
                        {task.at && <span>{formatDateTime(task.at, locale)}</span>}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <div className={s.side}>
            {actions.some((a) => a.show) && (
              <Card title={t("home.quick")}>
                <div className={s.actions}>
                  {actions
                    .filter((a) => a.show)
                    .map((a) =>
                      a.to ? (
                        <Link key={a.label} to={a.to} className={s.action}>
                          <span className={s.actionIcon}>{a.icon}</span>
                          <span>
                            <strong>{t(a.label)}</strong>
                            <span className={s.actionHint}>{t(a.hint)}</span>
                          </span>
                        </Link>
                      ) : (
                        <button key={a.label} type="button" className={s.action} onClick={a.onClick}>
                          <span className={s.actionIcon}>{a.icon}</span>
                          <span>
                            <strong>{t(a.label)}</strong>
                            <span className={s.actionHint}>{t(a.hint)}</span>
                          </span>
                        </button>
                      ),
                    )}
                </div>
              </Card>
            )}
            <Card title={t("home.tips")}>
              <ul className={s.tips}>
                <li>
                  <Kbd>Ctrl</Kbd> <Kbd>K</Kbd> — {t("home.tipPalette")}
                </li>
                {ai.data?.enabled && (
                  <li>
                    <Kbd>Ctrl</Kbd> <Kbd>J</Kbd> — {t("home.tipAssistant")}
                  </li>
                )}
                <li>{t("home.tipProject")}</li>
              </ul>
            </Card>
          </div>
        </div>
      </div>
    </PageBody>
  );
}
