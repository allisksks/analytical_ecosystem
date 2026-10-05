import { BarChart3, BookOpen, Database, FlaskConical, Zap } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router";
import { PageBody } from "../layout/AppShell";
import { useI18n, type TKey } from "../shared/i18n";
import s from "./HomePage.module.css";

interface ModuleCard {
  to: string;
  title: TKey;
  accent: string;
  icon: ReactNode;
  desc: { ru: string; en: string };
}

const MODULES: ModuleCard[] = [
  {
    to: "/data",
    title: "nav.data",
    accent: "var(--accent-data)",
    icon: <Database size={22} />,
    desc: {
      ru: "Коннекторы к хранилищам, каталог таблиц и семантический слой метрик.",
      en: "Connectors to warehouses, table catalog and the semantic metric layer.",
    },
  },
  {
    to: "/ems",
    title: "nav.ems",
    accent: "var(--accent-ems)",
    icon: <Zap size={22} />,
    desc: {
      ru: "Реестр событий с версиями, валидацией после релиза и алертами.",
      en: "Event registry with versions, post-release validation and alerts.",
    },
  },
  {
    to: "/bi",
    title: "nav.bi",
    accent: "var(--accent-bi)",
    icon: <BarChart3 size={22} />,
    desc: {
      ru: "Дашборды по ролям, конструктор когорт без SQL и SQL-редактор.",
      en: "Role dashboards, no-SQL cohort builder and a SQL editor.",
    },
  },
  {
    to: "/ab",
    title: "nav.ab",
    accent: "var(--accent-ab)",
    icon: <FlaskConical size={22} />,
    desc: {
      ru: "Дизайнер экспериментов, байесовский расчёт, контроль SRM.",
      en: "Experiment designer, Bayesian analysis, SRM checks.",
    },
  },
  {
    to: "/kb",
    title: "nav.kb",
    accent: "var(--accent-kb)",
    icon: <BookOpen size={22} />,
    desc: {
      ru: "Институциональная память: эксперименты, исследования, решения.",
      en: "Institutional memory: experiments, research, decisions.",
    },
  },
];

export function HomePage() {
  const { t, locale } = useI18n();
  return (
    <PageBody>
      <section className={s.hero}>
        <h1 className={s.title}>{t("app.name")}</h1>
        <p className={s.lead}>{t("app.tagline")}</p>
      </section>
      <div className={s.grid}>
        {MODULES.map((m) => (
          <Link key={m.to} to={m.to} className={s.card} style={{ ["--accent" as string]: m.accent }}>
            <span className={s.icon}>{m.icon}</span>
            <span className={s.cardTitle}>{t(m.title)}</span>
            <span className={s.cardDesc}>{m.desc[locale]}</span>
          </Link>
        ))}
      </div>
    </PageBody>
  );
}
