import clsx from "clsx";
import { ChevronDown, X } from "lucide-react";
import type { FilterIn } from "../../shared/api/types";
import { useI18n } from "../../shared/i18n";
import { Checkbox, Input, Popover, Spinner } from "../../shared/ui";
import { useDimensionValues, useDimensions, type GlobalFilters } from "./api";
import { isoDaysAgo, PRESETS, type Preset } from "./filters";
import s from "./bi.module.css";

export interface FilterState extends GlobalFilters {
  preset: Preset;
}

export function FilterBar({
  value,
  onChange,
  projectId,
  dimensionKeys = ["platform", "country", "source"],
}: {
  value: FilterState;
  onChange: (v: FilterState) => void;
  projectId: string | null;
  dimensionKeys?: string[];
}) {
  const { t } = useI18n();
  const dims = useDimensions();
  const setPreset = (p: Preset) =>
    onChange(
      p === "custom"
        ? { ...value, preset: p }
        : { ...value, preset: p, date_from: isoDaysAgo(p - 1), date_to: isoDaysAgo(0) },
    );
  const setFilter = (dimension: string, values: string[]) => {
    const rest = value.filters.filter((f) => f.dimension !== dimension);
    onChange({ ...value, filters: values.length ? [...rest, { dimension, op: "in", values }] : rest });
  };
  return (
    <div className={s.filterBar} role="group" aria-label={t("bi.period")}>
      <span className={s.filterLabel}>{t("bi.period")}</span>
      <div className={s.presets}>
        {PRESETS.map((p) => (
          <button
            key={p}
            type="button"
            className={clsx(s.preset, value.preset === p && s.presetActive)}
            aria-pressed={value.preset === p}
            onClick={() => setPreset(p)}
          >
            {t("bi.days", { n: p })}
          </button>
        ))}
        <button
          type="button"
          className={clsx(s.preset, value.preset === "custom" && s.presetActive)}
          aria-pressed={value.preset === "custom"}
          onClick={() => setPreset("custom")}
        >
          {t("bi.custom")}
        </button>
      </div>
      {value.preset === "custom" && (
        <>
          <Input
            type="date"
            className={s.dateInput}
            aria-label={t("bi.from")}
            value={value.date_from ?? ""}
            onChange={(e) => onChange({ ...value, date_from: e.target.value })}
          />
          <span className="muted">—</span>
          <Input
            type="date"
            className={s.dateInput}
            aria-label={t("bi.to")}
            value={value.date_to ?? ""}
            onChange={(e) => onChange({ ...value, date_to: e.target.value })}
          />
        </>
      )}
      <span style={{ width: 12 }} />
      {dimensionKeys.map((key) => (
        <DimensionChip
          key={key}
          dimKey={key}
          label={dims.data?.find((d) => d.key === key)?.name ?? key}
          projectId={projectId}
          selected={(value.filters.find((f) => f.dimension === key)?.values as string[] | undefined) ?? []}
          onChange={(vals) => setFilter(key, vals)}
        />
      ))}
    </div>
  );
}

function DimensionChip({
  dimKey,
  label,
  projectId,
  selected,
  onChange,
}: {
  dimKey: string;
  label: string;
  projectId: string | null;
  selected: string[];
  onChange: (v: string[]) => void;
}) {
  const { t } = useI18n();
  return (
    <Popover
      trigger={({ toggle, open }) => (
        <span style={{ display: "inline-flex", alignItems: "center" }}>
          <button
            type="button"
            className={clsx(s.chip, selected.length > 0 && s.chipActive)}
            onClick={toggle}
            aria-expanded={open}
          >
            {label}
            {selected.length > 0
              ? `: ${selected.slice(0, 2).join(", ")}${selected.length > 2 ? ` +${selected.length - 2}` : ""}`
              : ""}
            <ChevronDown size={14} />
          </button>
          {selected.length > 0 && (
            <button
              type="button"
              className={s.chip}
              style={{ marginLeft: 2, padding: "0 6px" }}
              aria-label={t("bi.clear")}
              onClick={() => onChange([])}
            >
              <X size={12} />
            </button>
          )}
        </span>
      )}
    >
      {() => <ChipValues dimKey={dimKey} projectId={projectId} selected={selected} onChange={onChange} />}
    </Popover>
  );
}

function ChipValues({
  dimKey,
  projectId,
  selected,
  onChange,
}: {
  dimKey: string;
  projectId: string | null;
  selected: string[];
  onChange: (v: string[]) => void;
}) {
  const values = useDimensionValues(dimKey, projectId);
  if (values.isPending)
    return (
      <div className={s.chipValues}>
        <Spinner />
      </div>
    );
  return (
    <div className={s.chipValues}>
      {(values.data ?? []).map((v) => {
        const val = String(v);
        return (
          <Checkbox
            key={val}
            label={val}
            checked={selected.includes(val)}
            onChange={(e) => onChange(e.target.checked ? [...selected, val] : selected.filter((x) => x !== val))}
          />
        );
      })}
    </div>
  );
}

export type { FilterIn };
