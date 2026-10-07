export interface Prop {
  type?: string;
  title?: string;
  description?: string;
  default?: unknown;
  enum?: string[];
  format?: string;
  minimum?: number;
  maximum?: number;
}

export interface ObjectSchema {
  required?: string[];
  properties?: Record<string, Prop>;
}

export type FormValue = Record<string, unknown>;

export function defaultsFor(schema: ObjectSchema | null | undefined): FormValue {
  const out: FormValue = {};
  for (const [k, p] of Object.entries(schema?.properties ?? {})) if (p.default !== undefined) out[k] = p.default;
  return out;
}
