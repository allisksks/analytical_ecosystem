import { Sparkles } from "lucide-react";
import { useState } from "react";
import { useI18n } from "../../shared/i18n";
import { Badge, Button, ErrorBox, Field, Modal, Textarea } from "../../shared/ui";
import { useGenerateSql } from "./api";
import s from "./ai.module.css";

export function SqlAiDialog({
  projectId,
  sourceId,
  onInsert,
  onClose,
}: {
  projectId: string;
  sourceId: string;
  onInsert: (sql: string) => void;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const [question, setQuestion] = useState("");
  const gen = useGenerateSql();
  const out = gen.data;
  const generate = () => gen.mutate({ question, project_id: projectId, source_id: sourceId });
  return (
    <Modal
      open
      size="lg"
      title={t("ai.generateSql")}
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>{t("common.cancel")}</Button>
          {out ? (
            <Button
              variant="primary"
              onClick={() => {
                onInsert(out.sql);
                onClose();
              }}
            >
              {t("ai.insert")}
            </Button>
          ) : (
            <Button
              variant="primary"
              icon={<Sparkles size={16} />}
              loading={gen.isPending}
              disabled={question.trim().length < 3}
              onClick={generate}
            >
              {t("ai.generate")}
            </Button>
          )}
        </>
      }
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <Field label={t("ai.sqlQuestion")} hint={t("ai.sqlHint")}>
          <Textarea
            rows={3}
            autoFocus
            placeholder={t("ai.sqlPlaceholder")}
            value={question}
            onChange={(e) => {
              setQuestion(e.target.value);
              if (gen.data) gen.reset();
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && question.trim().length >= 3) generate();
            }}
          />
        </Field>
        {gen.error && <ErrorBox>{gen.error.message}</ErrorBox>}
        {out && (
          <>
            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              <Badge tone={out.valid ? "pos" : "neg"} dot>
                {out.valid ? t("ai.valid") : t("ai.invalid")}
              </Badge>
              <span className="muted" style={{ fontSize: 12 }}>
                {t("ai.model", { model: out.model, ms: Math.round(out.latency_ms) })}
              </span>
            </div>
            <pre className={s.sqlBox}>{out.sql}</pre>
            {out.error && <ErrorBox>{out.error}</ErrorBox>}
            {out.explanation && <div>{out.explanation}</div>}
            {out.examples.length > 0 && (
              <div className="muted" style={{ fontSize: 12 }}>
                {t("ai.examplesUsed", { list: out.examples.join(", ") })}
              </div>
            )}
          </>
        )}
      </div>
    </Modal>
  );
}
