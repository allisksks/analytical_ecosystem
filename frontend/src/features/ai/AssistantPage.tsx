import { useSearchParams } from "react-router";
import { PageBody } from "../../layout/AppShell";
import { useI18n } from "../../shared/i18n";
import { PageHeader } from "../../shared/ui";
import { AssistantChat } from "./AssistantChat";
import s from "./ai.module.css";

export function AssistantPage() {
  const { t } = useI18n();
  const [params] = useSearchParams();
  return (
    <PageBody>
      <div className={s.pageWrap}>
        <PageHeader title={t("ai.title")} subtitle={t("ai.subtitle")} />
        <AssistantChat request={params.get("q") ? { q: params.get("q")!, n: 1 } : null} />
      </div>
    </PageBody>
  );
}
