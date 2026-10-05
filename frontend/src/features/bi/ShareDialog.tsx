import { Copy } from "lucide-react";
import { useState } from "react";
import type { Dashboard } from "../../shared/api/types";
import { useI18n } from "../../shared/i18n";
import { formatDateTime } from "../../shared/lib/format";
import { Button, ErrorBox, Field, Input, Modal, useToast } from "../../shared/ui";
import { useBiMutations } from "./api";

export function ShareDialog({ dashboard, onClose }: { dashboard: Dashboard; onClose: () => void }) {
  const { t, locale } = useI18n();
  const toast = useToast();
  const m = useBiMutations();
  const [ttl, setTtl] = useState(7);
  const [link, setLink] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const create = async () => {
    setError(null);
    try {
      const res = await m.share.mutateAsync({ dashId: dashboard.id, ttl });
      setLink(`${window.location.origin}/share/${res.token}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };
  return (
    <Modal
      open
      title={t("bi.shareTitle")}
      onClose={onClose}
      footer={
        <>
          {dashboard.shared && (
            <Button variant="ghost" onClick={() => m.unshare.mutate(dashboard.id, { onSuccess: () => setLink(null) })}>
              {t("bi.shareRevoke")}
            </Button>
          )}
          <Button variant="primary" onClick={() => void create()} loading={m.share.isPending}>
            {t("bi.shareCreate", { n: ttl })}
          </Button>
        </>
      }
    >
      <p className="muted" style={{ marginBottom: 16 }}>
        {t("bi.shareHint")}
      </p>
      {error && <ErrorBox>{error}</ErrorBox>}
      {dashboard.shared && dashboard.share_expires_at && !link && (
        <p style={{ marginBottom: 12 }}>
          {t("bi.shareUntil", { date: formatDateTime(dashboard.share_expires_at, locale) })}
        </p>
      )}
      <Field label={t("admin.ttlDays")}>
        <Input type="number" min={1} max={90} value={ttl} onChange={(e) => setTtl(Number(e.target.value))} />
      </Field>
      {link && (
        <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
          <Input readOnly value={link} onFocus={(e) => e.target.select()} />
          <Button
            icon={<Copy size={16} />}
            onClick={() => void navigator.clipboard.writeText(link).then(() => toast.success("OK"))}
            aria-label="Copy"
          />
        </div>
      )}
    </Modal>
  );
}
