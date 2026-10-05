import clsx from "clsx";
import { Eye, ShieldAlert, Table2 } from "lucide-react";
import { useMemo, useState } from "react";
import { useSearchParams } from "react-router";
import { SourceSelect } from "./SourceSelect";
import { useSelectedSource } from "./useSelectedSource";
import type { CatalogTable } from "../../shared/api/types";
import { useI18n } from "../../shared/i18n";
import { formatDateTime, formatNumber } from "../../shared/lib/format";
import {
  Badge,
  Card,
  Checkbox,
  EmptyState,
  Field,
  Input,
  PageSpinner,
  Table,
  Textarea,
  useToast,
} from "../../shared/ui";
import { useCan } from "../auth/AuthProvider";
import { useCatalog, useDataMutations } from "./api";
import s from "./data.module.css";

export function CatalogPage() {
  const { t, locale } = useI18n();
  const { sources, source } = useSelectedSource();
  const catalog = useCatalog(source?.id);
  const [params, setParams] = useSearchParams();
  const [q, setQ] = useState("");
  const tables = useMemo(
    () => (catalog.data ?? []).filter((x) => !q || x.name.toLowerCase().includes(q.toLowerCase())),
    [catalog.data, q],
  );
  const selected = catalog.data?.find((x) => x.id === params.get("table")) ?? tables[0];
  if (sources.isPending) return <PageSpinner />;
  if (!source)
    return (
      <Card>
        <EmptyState title={t("data.noSources")} />
      </Card>
    );
  return (
    <div className={s.catalog}>
      <Card padded={false}>
        <div style={{ padding: 12, display: "grid", gap: 8 }}>
          <SourceSelect />
          <Input placeholder={t("data.searchTables")} value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        {catalog.isPending ? (
          <PageSpinner />
        ) : (
          <div className={s.tableList} role="listbox" aria-label={t("data.catalog")}>
            {tables.map((x) => (
              <button
                key={x.id}
                role="option"
                aria-selected={x.id === selected?.id}
                className={clsx(s.tableItem, x.id === selected?.id && s.tableItemActive)}
                onClick={() =>
                  setParams((p) => {
                    p.set("table", x.id);
                    return p;
                  })
                }
              >
                {x.kind === "view" ? <Eye size={14} /> : <Table2 size={14} />}
                {x.schema_name !== "main" && x.schema_name !== "public" ? `${x.schema_name}.` : ""}
                {x.name}
                <span className={s.tableItemCount}>{formatNumber(x.row_count, locale)}</span>
              </button>
            ))}
          </div>
        )}
      </Card>
      {selected ? (
        <TableDetail key={selected.id} table={selected} />
      ) : (
        <Card>
          <EmptyState title={t("data.chooseTable")} />
        </Card>
      )}
    </div>
  );
}

function TableDetail({ table }: { table: CatalogTable }) {
  const { t, locale } = useI18n();
  const can = useCan();
  const toast = useToast();
  const m = useDataMutations();
  const editable = can("catalog:edit");
  const [description, setDescription] = useState(table.description);
  const [owner, setOwner] = useState(table.owner);
  const saveTable = (body: { description?: string; owner?: string }) =>
    m.patchTable.mutate({ id: table.id, body, sourceId: table.source_id }, { onError: (e) => toast.error(e.message) });
  return (
    <Card
      title={
        <code>
          {table.schema_name}.{table.name}
        </code>
      }
      subtitle={
        <>
          {formatNumber(table.row_count, locale)} {t("data.rowsApprox").replace("≈ ", "")} · {t("data.modified")}{" "}
          {formatDateTime(table.last_modified, locale)}
        </>
      }
      actions={<Badge>{table.kind}</Badge>}
    >
      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 16, marginBottom: 20 }}>
        <Field
          label={t("common.description")}
          hint={table.source_comment ? `${t("data.sourceComment")}: ${table.source_comment}` : undefined}
        >
          <Textarea
            value={description}
            disabled={!editable}
            onChange={(e) => setDescription(e.target.value)}
            onBlur={() => description !== table.description && saveTable({ description })}
          />
        </Field>
        <Field label={t("data.owner")}>
          <Input
            value={owner}
            disabled={!editable}
            onChange={(e) => setOwner(e.target.value)}
            onBlur={() => owner !== table.owner && saveTable({ owner })}
          />
        </Field>
      </div>
      <Table compact>
        <thead>
          <tr>
            <th>{t("data.column")}</th>
            <th>{t("data.type")}</th>
            <th style={{ width: "50%" }}>{t("common.description")}</th>
            <th title={t("data.piiHint")}>
              <ShieldAlert size={14} /> {t("data.pii")}
            </th>
          </tr>
        </thead>
        <tbody>
          {table.columns
            .filter((c) => c.present)
            .map((c) => (
              <ColumnRow key={c.id} sourceId={table.source_id} column={c} editable={editable} />
            ))}
        </tbody>
      </Table>
    </Card>
  );
}

function ColumnRow({
  column,
  sourceId,
  editable,
}: {
  column: CatalogTable["columns"][number];
  sourceId: string;
  editable: boolean;
}) {
  const { t } = useI18n();
  const toast = useToast();
  const m = useDataMutations();
  const [description, setDescription] = useState(column.description);
  const patch = (body: { description?: string; is_pii?: boolean }) =>
    m.patchColumn.mutate({ id: column.id, body, sourceId }, { onError: (e) => toast.error(e.message) });
  return (
    <tr>
      <td>
        <code>{column.name}</code>
      </td>
      <td className="muted">
        <code>{column.data_type}</code>
      </td>
      <td>
        <input
          className={s.inlineInput}
          aria-label={`${t("common.description")}: ${column.name}`}
          value={description}
          placeholder={column.source_comment || "—"}
          disabled={!editable}
          onChange={(e) => setDescription(e.target.value)}
          onBlur={() => description !== column.description && patch({ description })}
        />
      </td>
      <td>
        <Checkbox
          label={<span className="visually-hidden">{t("data.pii")}</span>}
          checked={column.is_pii}
          disabled={!editable}
          onChange={(e) => patch({ is_pii: e.target.checked })}
        />
      </td>
    </tr>
  );
}
