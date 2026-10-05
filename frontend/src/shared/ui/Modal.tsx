import clsx from "clsx";
import { X } from "lucide-react";
import type { ReactNode } from "react";
import { useEffect, useRef } from "react";
import { IconButton } from "./Button";
import s from "./Modal.module.css";

/** Accessible modal built on the native <dialog> element (focus trap and Esc handling for free). */
export function Modal({
  open,
  title,
  onClose,
  children,
  footer,
  size = "md",
}: {
  open: boolean;
  title: ReactNode;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  size?: "sm" | "md" | "lg" | "xl";
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (open && !el.open) el.showModal?.();
    if (!open && el.open) el.close?.();
  }, [open]);
  if (!open) return null;
  return (
    <dialog
      ref={ref}
      className={clsx(s.dialog, s[size])}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      onClick={(e) => {
        if (e.target === ref.current) onClose();
      }}
      aria-labelledby="modal-title"
    >
      <div className={s.inner}>
        <header className={s.head}>
          <h2 id="modal-title" className={s.title}>
            {title}
          </h2>
          <IconButton label="Close" onClick={onClose} size="sm">
            <X size={16} />
          </IconButton>
        </header>
        <div className={s.body}>{children}</div>
        {footer && <footer className={s.foot}>{footer}</footer>}
      </div>
    </dialog>
  );
}
