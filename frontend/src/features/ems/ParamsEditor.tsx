import { Plus, Trash2 } from "lucide-react";
import type { ParamIn } from "../../shared/api/types";
import { useI18n } from "../../shared/i18n";
import { Button, Checkbox, IconButton, Input, Select } from "../../shared/ui";
import s from "./ems.module.css";

const TYPES: ParamIn["type"][] = ["string", "int", "float", "bool", "enum", "timestamp", "json"];

export function ParamsEditor({ value, onChange }: { value: ParamIn[]; onChange: (v: ParamIn[]) => void }) {
  const { t } = useI18n();
  const set = (i: number, patch: Partial<ParamIn>) => onChange(value.map((p, j) => (j === i ? { ...p, ...patch } : p)));
  return (
    <div>
      {value.map((p, i) => (
        <div key={i} className={s.paramRow}>
          <Input
            mono
            aria-label={t("ems.param")}
            placeholder="param_name"
            value={p.name}
            onChange={(e) => set(i, { name: e.target.value })}
          />
          <Select
            aria-label={t("ems.type")}
            value={p.type}
            onChange={(e) => set(i, { type: e.target.value as ParamIn["type"] })}
          >
            {TYPES.map((x) => (
              <option key={x} value={x}>
                {x}
              </option>
            ))}
          </Select>
          <Checkbox
            label={<span className="visually-hidden">{t("ems.required")}</span>}
            checked={!!p.required}
            onChange={(e) => set(i, { required: e.target.checked })}
          />
          <Input
            aria-label={t("common.description")}
            placeholder={t("common.description")}
            value={p.description ?? ""}
            onChange={(e) => set(i, { description: e.target.value })}
          />
          <Input
            aria-label="enum"
            placeholder={p.type === "enum" ? "a, b, c" : "—"}
            disabled={p.type !== "enum"}
            value={(p.enum ?? []).join(", ")}
            onChange={(e) =>
              set(i, {
                enum: e.target.value
                  .split(",")
                  .map((x) => x.trim())
                  .filter(Boolean),
              })
            }
          />
          <IconButton label={t("common.delete")} onClick={() => onChange(value.filter((_, j) => j !== i))}>
            <Trash2 size={16} />
          </IconButton>
        </div>
      ))}
      <Button
        size="sm"
        icon={<Plus size={14} />}
        onClick={() => onChange([...value, { name: "", type: "string", required: false, description: "", enum: [] }])}
      >
        {t("ems.addParam")}
      </Button>
    </div>
  );
}
