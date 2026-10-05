import { ChevronDown, Folder, FolderOpen } from "lucide-react";
import { useI18n } from "../../shared/i18n";
import { MenuGroup, MenuItem, Popover } from "../../shared/ui";
import { useProject } from "./ProjectProvider";
import s from "./ProjectPicker.module.css";

export function ProjectPicker() {
  const { t } = useI18n();
  const { projects, project, setProjectId } = useProject();
  if (!projects.length) return null;
  const groups = new Map<string, typeof projects>();
  for (const p of projects) groups.set(p.group_name || "—", [...(groups.get(p.group_name || "—") ?? []), p]);
  return (
    <Popover
      align="end"
      trigger={({ toggle, open }) => (
        <button className={s.trigger} onClick={toggle} aria-expanded={open} aria-haspopup="menu">
          <span className={s.texts}>
            <span className={s.name}>{project?.name ?? t("projects.choose")}</span>
            {project?.group_name && <span className={s.meta}>{project.group_name}</span>}
          </span>
          <ChevronDown size={16} />
        </button>
      )}
    >
      {(close) =>
        [...groups.entries()].map(([group, items]) => (
          <MenuGroup key={group} label={group}>
            {items.map((p) => (
              <MenuItem
                key={p.id}
                active={p.id === project?.id}
                icon={p.id === project?.id ? <FolderOpen size={16} /> : <Folder size={16} />}
                onClick={() => {
                  setProjectId(p.id);
                  close();
                }}
              >
                {p.name}
              </MenuItem>
            ))}
          </MenuGroup>
        ))
      }
    </Popover>
  );
}
