import { CheckCircle2, Database, Plus, TriangleAlert } from "lucide-react";
import { typeIcon } from "./typeIcon";
import { useState } from "react";
import type { Source } from "../../shared/api/types";
import { useI18n } from "../../shared/i18n";
import { formatDateTime, formatNumber } from "../../shared/lib/format";
import { Badge, Button, Card, EmptyState, PageSpinner } from "../../shared/ui";
import { useCan } from "../auth/AuthProvider";
import { SourceDialog } from "./SourceDialog";
import { useSources } from "./api";
import s from "./data.module.css";

export function SourcesPage() {
  const { t, locale } = useI18n();
  const can = useCan();
  const sources = useSources();
  const [open, setOpen] = useState<Source | "new" | null>(null);
  if (sources.isPending) return <PageSpinner />;
  const canManage = can("connectors:manage");
  return (
    <>
      {canManage && (
        <div className={s.row} style={{ justifyContent: "flex-end", marginBottom: 16 }}>
          <Button variant="primary" icon={<Plus size={16} />} onClick={() => setOpen("new")}>
            {t("data.connect")}
          </Button>
        </div>
      )}
      {!sources.data?.length ? (
        <Card>
          <EmptyState
            icon={<Database size={26} />}
            title={t("data.noSources")}
            description={t("data.noSourcesHint")}
            action={
              canManage && (
                <Button variant="primary" onClick={() => setOpen("new")}>
                  {t("data.connect")}
                </Button>
              )
            }
          />
        </Card>
      ) : (
        <div className={s.grid}>
          {sources.data.map((src) => (
            <button key={src.id} className={s.sourceCard} onClick={() => setOpen(src)}>
              <div className={s.sourceHead}>
                <span className={s.typeIcon}>{typeIcon(src.type)}</span>
                <div style={{ minWidth: 0 }}>
                  <div className={s.sourceName}>{src.name}</div>
                  <div className={s.meta}>
                    <span>{src.type}</span>
                    <span>{src.mode}</span>
                  </div>
                </div>
                <span style={{ marginLeft: "auto" }}>
                  {src.status === "error" ? (
                    <Badge tone="neg" dot>
                      error
                    </Badge>
                  ) : src.status === "ok" ? (
                    <Badge tone="pos" dot>
                      ok
                    </Badge>
                  ) : (
                    <Badge>new</Badge>
                  )}
                </span>
              </div>
              <div className={s.meta}>
                <span>
                  {formatNumber(src.table_count, locale)} {t("data.tables")}
                </span>
                {src.catalog_refreshed_at && (
                  <span>
                    {src.status === "ok" ? <CheckCircle2 size={12} /> : <TriangleAlert size={12} />}{" "}
                    {formatDateTime(src.catalog_refreshed_at, locale)}
                  </span>
                )}
                {src.is_demo && <Badge tone="violet">demo</Badge>}
              </div>
              {src.last_error && <div className={s.error}>{src.last_error}</div>}
            </button>
          ))}
        </div>
      )}
      {open && <SourceDialog source={open === "new" ? null : open} onClose={() => setOpen(null)} />}
    </>
  );
}
