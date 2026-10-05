import { Maximize2, Sparkles, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { useShell } from "../../layout/shell";
import { useI18n } from "../../shared/i18n";
import { IconButton } from "../../shared/ui";
import { useCan } from "../auth/AuthProvider";
import { AssistantChat } from "./AssistantChat";
import { useAiStatus } from "./api";
import s from "./ai.module.css";

/** Top-bar button: the assistant is one click (or Ctrl+J) away from any page. */
export function AssistantButton() {
  const { t } = useI18n();
  const can = useCan();
  const status = useAiStatus();
  const { assistantOpen, openAssistant, closeAssistant } = useShell();
  if (!status.data?.enabled || !can("kb:ask")) return null;
  return (
    <button
      type="button"
      className={s.topButton}
      aria-pressed={assistantOpen}
      aria-keyshortcuts="Control+J"
      onClick={() => (assistantOpen ? closeAssistant() : openAssistant())}
    >
      <Sparkles size={16} />
      <span>{t("ai.title")}</span>
    </button>
  );
}

/** Side panel with the same chat as the assistant page; the conversation survives closing the panel. */
export function AssistantDrawer() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const { assistantOpen, closeAssistant, request } = useShell();
  // mounted on first open and kept afterwards, so the conversation survives closing the panel
  const [mounted, setMounted] = useState(false);
  if (assistantOpen && !mounted) setMounted(true);
  const panel = useRef<HTMLElement>(null);

  useEffect(() => {
    if (assistantOpen) panel.current?.querySelector("textarea")?.focus();
  }, [assistantOpen]);

  if (!mounted) return null;
  return (
    <aside
      ref={panel}
      className={s.drawer}
      hidden={!assistantOpen}
      aria-label={t("ai.title")}
      onKeyDown={(e) => e.key === "Escape" && closeAssistant()}
    >
      <header className={s.drawerHead}>
        <Sparkles size={18} aria-hidden />
        <strong>{t("ai.title")}</strong>
        <span style={{ flex: 1 }} />
        <IconButton
          size="sm"
          variant="ghost"
          label={t("ai.openPage")}
          onClick={() => {
            closeAssistant();
            navigate("/assistant");
          }}
        >
          <Maximize2 size={15} />
        </IconButton>
        <IconButton size="sm" variant="ghost" label={t("common.close")} onClick={closeAssistant}>
          <X size={16} />
        </IconButton>
      </header>
      <div className={s.drawerBody}>
        <AssistantChat compact request={request} />
      </div>
    </aside>
  );
}
