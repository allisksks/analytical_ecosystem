import s from "./Spinner.module.css";

export function Spinner({ size = 18, label }: { size?: number; label?: string }) {
  return (
    <span className={s.wrap} role="status" aria-label={label ?? "loading"}>
      <span className={s.spinner} style={{ width: size, height: size }} />
    </span>
  );
}

export function PageSpinner() {
  return (
    <div className={s.page}>
      <Spinner size={28} />
    </div>
  );
}
