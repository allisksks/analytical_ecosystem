import { History, Plus } from "lucide-react";
import { useMemo, useState } from "react";
import { useSearchParams } from "react-router";
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import { api } from "../../shared/api/client";
import type { MetricOut, Schemas } from "../../shared/api/types";
import { useI18n } from "../../shared/i18n";
import { formatDateTime } from "../../shared/lib/format";
import {
  Badge,
  Button,
  Card,
  ErrorBox,
  Field,
  Input,
  Modal,
  PageSpinner,
  Select,
  Table,
  Textarea,
  useToast,
} from "../../shared/ui";
import { useCan } from "../auth/AuthProvider";
import { useMetrics } from "../bi/api";

type Format = Schemas["MetricIn"]["format"];

/** Semantic layer registry: one definition per metric, used by dashboards, experiments and the assistant. */
export function MetricsPage() {
  const { t } = useI18n();
  const can = useCan();
  const metrics = useMetrics();
  const [params, setParams] = useSearchParams();
  const [q, setQ] = useState("");
  const [creating, setCreating] = useState(false);
  const selected = metrics.data?.find((x) => x.key === params.get("key"));
  const list = useMemo(
    () =>
      (metrics.data ?? []).filter(
        (x) => !q || `${x.name} ${x.key} ${x.description}`.toLowerCase().includes(q.toLowerCase()),
      ),
    [metrics.data, q],
  );
  if (metrics.isPending) return <PageSpinner />;
  return (
    <Card
      title={t("data.metrics")}
      actions={
        <>
          <Input
            placeholder={t("data.searchMetrics")}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            style={{ width: 260 }}
          />
          {can("semantic:edit") && (
            <Button variant="primary" icon={<Plus size={16} />} onClick={() => setCreating(true)}>
              {t("data.newMetric")}
            </Button>
          )}
        </>
      }
    >
      <Table clickable>
        <thead>
          <tr>
            <th>{t("common.name")}</th>
            <th>{t("data.metricKey")}</th>
            <th>{t("data.table")}</th>
            <th>{t("data.formula")}</th>
            <th>v</th>
          </tr>
        </thead>
        <tbody>
          {list.map((x) => (
            <tr key={x.id} onClick={() => setParams({ key: x.key })}>
              <td>
                <strong>{x.name}</strong>
                <div className="muted" style={{ fontSize: 12 }}>
                  {x.description}
                </div>
              </td>
              <td>
                <code>{x.key}</code>
              </td>
              <td>
                <code>{x.table}</code>
              </td>
              <td style={{ maxWidth: 420 }}>
                <code style={{ fontSize: 12 }}>{x.expression}</code>
              </td>
              <td>
                <Badge mono>v{x.version}</Badge>
              </td>
            </tr>
          ))}
        </tbody>
      </Table>
      {(selected || creating) && (
        <MetricDialog
          metric={creating ? null : (selected ?? null)}
          editable={can("semantic:edit")}
          onClose={() => {
            setCreating(false);
            setParams({});
          }}
        />
      )}
    </Card>
  );
}

function MetricDialog({
  metric,
  editable,
  onClose,
}: {
  metric: MetricOut | null;
  editable: boolean;
  onClose: () => void;
}) {
  const { t, locale } = useI18n();
  const toast = useToast();
  const qc = useQueryClient();
  const [form, setForm] = useState({
    key: metric?.key ?? "",
    name: metric?.name ?? "",
    description: metric?.description ?? "",
    table: metric?.table ?? "",
    time_column: metric?.time_column ?? "",
    expression: metric?.expression ?? "",
    filters: metric?.filters ?? "",
    maturity_days: metric?.maturity_days ?? 0,
    format: (metric?.format ?? "number") as Format,
  });
  const [showVersions, setShowVersions] = useState(false);
  const versions = useQuery({
    queryKey: ["semantic", "versions", metric?.id],
    queryFn: async () =>
      (await api.GET("/api/v1/semantic/metrics/{metric_id}/versions", { params: { path: { metric_id: metric!.id } } }))
        .data!,
    enabled: showVersions && !!metric,
  });
  const save = useMutation({
    mutationFn: async () => {
      const { key, ...rest } = form;
      return metric
        ? (
            await api.PATCH("/api/v1/semantic/metrics/{metric_id}", {
              params: { path: { metric_id: metric.id } },
              body: rest,
            })
          ).data!
        : (
            await api.POST("/api/v1/semantic/metrics", {
              body: { key, ...rest, default_dimensions: [], tags: [], owner: "" },
            })
          ).data!;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["semantic"] });
      toast.success(t("admin.saved"));
      onClose();
    },
  });
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) =>
    setForm({ ...form, [k]: k === "maturity_days" ? Number(e.target.value) : e.target.value });
  return (
    <Modal
      open
      size="lg"
      title={metric ? metric.name : t("data.newMetric")}
      onClose={onClose}
      footer={
        <>
          {metric && (
            <Button variant="ghost" icon={<History size={16} />} onClick={() => setShowVersions((v) => !v)}>
              v{metric.version}
            </Button>
          )}
          <Button onClick={onClose}>{t("common.close")}</Button>
          {editable && (
            <Button variant="primary" onClick={() => save.mutate()} loading={save.isPending}>
              {t("common.save")}
            </Button>
          )}
        </>
      }
    >
      {save.error && <ErrorBox>{save.error.message}</ErrorBox>}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
        <Field label={t("data.metricKey")}>
          <Input mono value={form.key} disabled={!!metric || !editable} onChange={set("key")} />
        </Field>
        <Field label={t("common.name")}>
          <Input value={form.name} disabled={!editable} onChange={set("name")} />
        </Field>
        <Field label={t("common.description")} className="full">
          <Textarea
            value={form.description}
            disabled={!editable}
            onChange={set("description")}
            style={{ minHeight: 56 }}
          />
        </Field>
        <Field label={t("data.table")}>
          <Input mono value={form.table} disabled={!editable} onChange={set("table")} />
        </Field>
        <Field label={t("data.timeColumn")}>
          <Input mono value={form.time_column} disabled={!editable} onChange={set("time_column")} />
        </Field>
        <Field label={t("data.formula")} className="full">
          <Textarea
            mono
            value={form.expression}
            disabled={!editable}
            onChange={set("expression")}
            style={{ minHeight: 70 }}
          />
        </Field>
        <Field label={t("data.filtersExpr")}>
          <Input mono value={form.filters} disabled={!editable} onChange={set("filters")} />
        </Field>
        <Field label={t("data.maturity")}>
          <Input
            type="number"
            min={0}
            value={form.maturity_days}
            disabled={!editable}
            onChange={set("maturity_days")}
          />
        </Field>
        <Field label={t("data.format")}>
          <Select value={form.format} disabled={!editable} onChange={set("format")}>
            {["number", "percent", "currency", "decimal"].map((f) => (
              <option key={f} value={f}>
                {f}
              </option>
            ))}
          </Select>
        </Field>
      </div>
      {showVersions && (
        <Table compact className="" maxHeight={240}>
          <tbody>
            {versions.data?.map((v) => (
              <tr key={v.version}>
                <td>
                  <Badge mono>v{v.version}</Badge>
                </td>
                <td className="muted">{formatDateTime(v.created_at, locale)}</td>
                <td>{v.author}</td>
                <td>
                  <code style={{ fontSize: 12 }}>{String(v.definition.expression ?? "")}</code>
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </Modal>
  );
}
