import { useState } from "react";
import { Field, Input, Select, Switch, Textarea } from "../../shared/ui";
import type { FormValue, ObjectSchema } from "./schemaDefaults";

/** Renders a connector form from the JSON Schema published by the backend plugin. */
export function JsonSchemaForm({
  schema,
  value,
  onChange,
  secretKeptHint,
  hasStoredSecrets,
}: {
  schema: ObjectSchema;
  value: FormValue;
  onChange: (v: FormValue) => void;
  secretKeptHint: string;
  hasStoredSecrets?: boolean;
}) {
  const required = new Set(schema.required ?? []);
  const set = (k: string, v: unknown) => onChange({ ...value, [k]: v });
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
      {Object.entries(schema.properties ?? {}).map(([key, p]) => {
        const label = p.title ?? key;
        const isSecret = p.format === "password";
        const wide = p.type === "object" || (p.description?.length ?? 0) > 60;
        let control;
        if (p.type === "boolean") {
          return (
            <div key={key} style={{ alignSelf: "end", paddingBottom: 8 }}>
              <Switch checked={Boolean(value[key])} onChange={(v) => set(key, v)} label={label} />
            </div>
          );
        } else if (p.enum) {
          control = (
            <Select value={String(value[key] ?? "")} onChange={(e) => set(key, e.target.value)}>
              {p.enum.map((o) => (
                <option key={o} value={o}>
                  {o}
                </option>
              ))}
            </Select>
          );
        } else if (p.type === "object") {
          control = <JsonField value={value[key]} onChange={(v) => set(key, v)} />;
        } else if (p.type === "integer") {
          control = (
            <Input
              type="number"
              min={p.minimum}
              max={p.maximum}
              value={value[key] === undefined ? "" : String(value[key])}
              onChange={(e) => set(key, e.target.value === "" ? undefined : Number(e.target.value))}
            />
          );
        } else if (isSecret && key.endsWith("_json")) {
          control = (
            <Textarea
              mono
              placeholder={hasStoredSecrets ? secretKeptHint : ""}
              value={String(value[key] ?? "")}
              onChange={(e) => set(key, e.target.value)}
            />
          );
        } else {
          control = (
            <Input
              type={isSecret ? "password" : "text"}
              autoComplete={isSecret ? "new-password" : "off"}
              placeholder={isSecret && hasStoredSecrets ? secretKeptHint : undefined}
              value={String(value[key] ?? "")}
              onChange={(e) => set(key, e.target.value)}
            />
          );
        }
        return (
          <Field
            key={key}
            label={label}
            hint={p.description}
            required={required.has(key) && !(isSecret && hasStoredSecrets)}
            className={wide ? "full" : undefined}
          >
            {control}
          </Field>
        );
      })}
    </div>
  );
}

function JsonField({ value, onChange }: { value: unknown; onChange: (v: unknown) => void }) {
  const [text, setText] = useState(() => JSON.stringify(value ?? {}, null, 2));
  const [bad, setBad] = useState(false);
  return (
    <Textarea
      mono
      aria-invalid={bad || undefined}
      value={text}
      onChange={(e) => {
        setText(e.target.value);
        try {
          onChange(JSON.parse(e.target.value || "{}"));
          setBad(false);
        } catch {
          setBad(true);
        }
      }}
    />
  );
}
