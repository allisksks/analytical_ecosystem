import type { ChartData } from "../../shared/charts/buildOption";

export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function csvCell(v: unknown): string {
  const s = v === null || v === undefined ? "" : String(v);
  return /[",\n;]/.test(s) ? `"${s.replaceAll('"', '""')}"` : s;
}

export function downloadCsv(data: ChartData, filename: string): void {
  const lines = [data.columns.map((c) => csvCell(c.name)).join(","), ...data.rows.map((r) => r.map(csvCell).join(","))];
  saveBlob(new Blob(["﻿" + lines.join("\n")], { type: "text/csv;charset=utf-8" }), filename);
}

export function downloadDataUrl(dataUrl: string, filename: string): void {
  const a = document.createElement("a");
  a.href = dataUrl;
  a.download = filename;
  a.click();
}

export function slug(s: string): string {
  return (
    s
      .replace(/[^\p{L}\p{N}]+/gu, "_")
      .replace(/^_|_$/g, "")
      .slice(0, 60) || "export"
  );
}
