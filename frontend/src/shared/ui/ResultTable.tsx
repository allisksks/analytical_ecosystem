import { formatNumber } from "../lib/format";
import { Table } from "./Table";
import s from "./Table.module.css";

const MAX_RENDER = 1000;

function cell(v: unknown, locale: string): string {
  if (v === null || v === undefined) return "NULL";
  if (typeof v === "number") return formatNumber(v, locale, 6);
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

/** Read-only grid for query results (renders the first 1000 rows; export gives the rest). */
export function ResultTable({
  columns,
  rows,
  locale = "ru",
  maxHeight = 480,
}: {
  columns: { name: string; type: string }[];
  rows: unknown[][];
  locale?: string;
  maxHeight?: number | string;
}) {
  const numeric = columns.map((c) => /int|float|double|decimal|numeric|real|number|hugeint/i.test(c.type));
  return (
    <>
      <Table compact maxHeight={maxHeight}>
        <thead>
          <tr>
            <th className={s.num}>#</th>
            {columns.map((c, i) => (
              <th key={i} title={c.type} className={numeric[i] ? s.num : undefined}>
                {c.name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, MAX_RENDER).map((r, i) => (
            <tr key={i}>
              <td className={`${s.num} ${s.muted}`}>{i + 1}</td>
              {r.map((v, j) => (
                <td key={j} className={`${numeric[j] ? s.num : ""} ${v === null ? s.muted : ""} ${s.mono}`}>
                  {cell(v, locale)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </Table>
      {rows.length > MAX_RENDER && (
        <div className={s.muted} style={{ padding: 8, fontSize: 12 }}>
          {formatNumber(MAX_RENDER, locale)} / {formatNumber(rows.length, locale)}
        </div>
      )}
    </>
  );
}
