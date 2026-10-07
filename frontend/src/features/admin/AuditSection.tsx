import { useState } from "react";
import { useI18n } from "../../shared/i18n";
import { formatDateTime } from "../../shared/lib/format";
import { Badge, Button, Card, Input, PageSpinner, Table } from "../../shared/ui";
import { useAudit } from "./api";
import s from "./admin.module.css";

const PAGE = 50;

export function AuditSection() {
  const { t, locale } = useI18n();
  const [action, setAction] = useState("");
  const [offset, setOffset] = useState(0);
  const audit = useAudit({ action: action || undefined, offset });
  return (
    <Card title={t("admin.audit")}>
      <div className={s.toolbar}>
        <Input
          style={{ maxWidth: 320 }}
          placeholder={t("admin.filterAction")}
          value={action}
          onChange={(e) => {
            setAction(e.target.value);
            setOffset(0);
          }}
        />
      </div>
      {audit.isPending ? (
        <PageSpinner />
      ) : (
        <>
          <Table compact>
            <thead>
              <tr>
                <th>{t("admin.when")}</th>
                <th>{t("admin.who")}</th>
                <th>{t("admin.action")}</th>
                <th>{t("admin.resource")}</th>
                <th>{t("admin.outcome")}</th>
                <th>SQL</th>
              </tr>
            </thead>
            <tbody>
              {audit.data?.items.map((a) => (
                <tr key={a.id}>
                  <td style={{ whiteSpace: "nowrap" }}>{formatDateTime(a.ts, locale)}</td>
                  <td>{a.actor_label}</td>
                  <td>
                    <code>{a.action}</code>
                  </td>
                  <td className="muted">{a.resource_type && `${a.resource_type}:${a.resource_id.slice(0, 8)}`}</td>
                  <td>
                    <Badge tone={a.outcome === "success" ? "pos" : "neg"}>{a.outcome}</Badge>
                  </td>
                  <td className={s.sql} title={a.sql ?? ""}>
                    {a.sql && <code>{a.sql}</code>}
                    {a.row_count != null && <span className="muted"> · {a.row_count}</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
          <div className={s.pager}>
            <span>
              {offset + 1}–{Math.min(offset + PAGE, audit.data?.total ?? 0)} / {audit.data?.total ?? 0}
            </span>
            <Button size="sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
              ←
            </Button>
            <Button
              size="sm"
              disabled={offset + PAGE >= (audit.data?.total ?? 0)}
              onClick={() => setOffset(offset + PAGE)}
            >
              →
            </Button>
          </div>
        </>
      )}
    </Card>
  );
}
