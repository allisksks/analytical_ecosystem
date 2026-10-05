import clsx from "clsx";
import { BookOpen, Send, Sparkles, Square, ThumbsDown, ThumbsUp } from "lucide-react";
import { useRef, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router";
import { PageBody } from "../../layout/AppShell";
import { useI18n, type TKey } from "../../shared/i18n";
import {
  Button,
  Card,
  Checkbox,
  EmptyState,
  ErrorBox,
  IconButton,
  Markdown,
  PageHeader,
  Textarea,
  useToast,
} from "../../shared/ui";
import { useProject } from "../projects/ProjectProvider";
import { askStream, useAiStatus, useFeedback, type AiSource } from "./api";
import s from "./ai.module.css";

interface Turn {
  question: string;
  answer: string;
  sources: AiSource[];
  interactionId?: string;
  error?: string;
  streaming: boolean;
  rating?: -1 | 1;
}

const EXAMPLES: TKey[] = ["ai.example1", "ai.example2", "ai.example3"];

export function AssistantPage() {
  const { t } = useI18n();
  const toast = useToast();
  const status = useAiStatus();
  const { project } = useProject();
  const [params] = useSearchParams();
  const [question, setQuestion] = useState(params.get("q") ?? "");
  const [scoped, setScoped] = useState(false);
  const [turns, setTurns] = useState<Turn[]>([]);
  const abort = useRef<AbortController | null>(null);
  const feedback = useFeedback();
  const busy = turns.some((x) => x.streaming);

  const update = (i: number, patch: Partial<Turn> | ((t: Turn) => Partial<Turn>)) =>
    setTurns((all) => all.map((x, j) => (j === i ? { ...x, ...(typeof patch === "function" ? patch(x) : patch) } : x)));

  const ask = (q: string) => {
    const text = q.trim();
    if (!text || busy) return;
    const i = turns.length;
    setTurns((all) => [...all, { question: text, answer: "", sources: [], streaming: true }]);
    setQuestion("");
    const ctrl = new AbortController();
    abort.current = ctrl;
    void askStream(
      { question: text, project_id: scoped ? (project?.id ?? null) : null },
      {
        onSources: (sources) => update(i, { sources }),
        onDelta: (d) => update(i, (x) => ({ answer: x.answer + d })),
        onDone: (id) => update(i, { interactionId: id, streaming: false }),
        onError: (message) => update(i, { error: message }),
      },
      ctrl.signal,
    )
      .catch((e: Error) => {
        if (e.name !== "AbortError") update(i, { error: e.message });
      })
      .finally(() => update(i, { streaming: false }));
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    ask(question);
  };

  const rate = (i: number, rating: -1 | 1) => {
    const id = turns[i].interactionId;
    if (!id) return;
    feedback.mutate(
      { id, rating },
      {
        onSuccess: () => (update(i, { rating }), toast.success(t("ai.thanks"))),
        onError: (e) => toast.error(e.message),
      },
    );
  };

  if (status.data && !status.data.enabled)
    return (
      <PageBody>
        <PageHeader title={t("ai.title")} />
        <Card>
          <EmptyState icon={<Sparkles size={28} />} title={t("ai.disabledTitle")} description={t("ai.disabledText")} />
        </Card>
      </PageBody>
    );

  return (
    <PageBody>
      <div className={s.wrap}>
        <PageHeader title={t("ai.title")} subtitle={t("ai.subtitle")} />
        {turns.length === 0 && (
          <Card title={t("ai.examples")}>
            <div className={s.examples}>
              {EXAMPLES.map((k) => (
                <button key={k} type="button" className={s.example} onClick={() => ask(t(k))}>
                  {t(k)}
                </button>
              ))}
            </div>
          </Card>
        )}
        {turns.map((turn, i) => (
          <div key={i} className={s.turn}>
            <div className={s.question}>{turn.question}</div>
            <div className={s.answer} aria-live={turn.streaming ? "polite" : undefined} aria-busy={turn.streaming}>
              {turn.error && !turn.answer ? (
                <ErrorBox>{turn.error}</ErrorBox>
              ) : (
                <div className={clsx(turn.streaming && s.cursor)}>
                  <Markdown>{turn.answer || " "}</Markdown>
                </div>
              )}
              {turn.sources.length > 0 && (
                <div className={s.sources}>
                  <BookOpen size={14} aria-hidden />
                  <span className="muted">{t("ai.sources")}:</span>
                  {turn.sources.map((src) => (
                    <Link key={src.n} to={`/kb/${src.item_id}`} className={s.source}>
                      <span className={s.sourceN}>[{src.n}]</span>
                      {src.title}
                    </Link>
                  ))}
                </div>
              )}
              {turn.interactionId && (
                <div className={s.footer}>
                  <IconButton
                    size="sm"
                    variant={turn.rating === 1 ? "primary" : "ghost"}
                    label={t("ai.helpful")}
                    onClick={() => rate(i, 1)}
                  >
                    <ThumbsUp size={14} />
                  </IconButton>
                  <IconButton
                    size="sm"
                    variant={turn.rating === -1 ? "primary" : "ghost"}
                    label={t("ai.notHelpful")}
                    onClick={() => rate(i, -1)}
                  >
                    <ThumbsDown size={14} />
                  </IconButton>
                </div>
              )}
            </div>
          </div>
        ))}
        <Card>
          <form className={s.composer} onSubmit={submit}>
            <Textarea
              rows={3}
              aria-label={t("ai.ask")}
              placeholder={t("ai.placeholder")}
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  ask(question);
                }
              }}
            />
            <div className={s.composerRow}>
              <Checkbox
                label={`${t("ai.scopeProject")}${project ? ` (${project.name})` : ""}`}
                checked={scoped}
                disabled={!project}
                onChange={(e) => setScoped(e.target.checked)}
              />
              {busy ? (
                <Button variant="danger" icon={<Square size={14} />} onClick={() => abort.current?.abort()}>
                  {t("ai.stop")}
                </Button>
              ) : (
                <Button variant="primary" type="submit" icon={<Send size={16} />} disabled={!question.trim()}>
                  {t("ai.ask")}
                </Button>
              )}
            </div>
          </form>
        </Card>
      </div>
    </PageBody>
  );
}
