import { Plus } from "lucide-react";
import { useState } from "react";
import type { Project } from "../../shared/api/types";
import { useI18n } from "../../shared/i18n";
import {
  Badge,
  Button,
  Card,
  ErrorBox,
  Field,
  Input,
  Modal,
  PageSpinner,
  Switch,
  Table,
  Textarea,
  useToast,
} from "../../shared/ui";
import { useAdminMutations, useAllProjects } from "./api";
import s from "./admin.module.css";

export function ProjectsSection() {
  const { t } = useI18n();
  const projects = useAllProjects();
  const [editing, setEditing] = useState<Project | "new" | null>(null);
  if (projects.isPending) return <PageSpinner />;
  return (
    <Card
      title={t("admin.projects")}
      actions={
        <Button variant="primary" icon={<Plus size={16} />} onClick={() => setEditing("new")}>
          {t("admin.newProject")}
        </Button>
      }
    >
      <Table clickable>
        <thead>
          <tr>
            <th>{t("common.name")}</th>
            <th>{t("admin.key")}</th>
            <th>{t("admin.group")}</th>
            <th>{t("admin.dataScope")}</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {projects.data?.map((p) => (
            <tr key={p.id} onClick={() => setEditing(p)}>
              <td>
                <strong>{p.name}</strong>
              </td>
              <td>
                <code>{p.key}</code>
              </td>
              <td>{p.group_name}</td>
              <td>
                <code>{JSON.stringify(p.data_scope)}</code>
              </td>
              <td>{p.archived && <Badge>archived</Badge>}</td>
            </tr>
          ))}
        </tbody>
      </Table>
      {editing && <ProjectModal project={editing === "new" ? null : editing} onClose={() => setEditing(null)} />}
    </Card>
  );
}

function ProjectModal({ project, onClose }: { project: Project | null; onClose: () => void }) {
  const { t } = useI18n();
  const toast = useToast();
  const m = useAdminMutations();
  const [key, setKey] = useState(project?.key ?? "");
  const [name, setName] = useState(project?.name ?? "");
  const [group, setGroup] = useState(project?.group_name ?? "");
  const [description, setDescription] = useState(project?.description ?? "");
  const [scope, setScope] = useState(JSON.stringify(project?.data_scope ?? {}, null, 2));
  const [archived, setArchived] = useState(project?.archived ?? false);
  const [error, setError] = useState<string | null>(null);
  const save = async () => {
    setError(null);
    let data_scope: Record<string, unknown[]>;
    try {
      data_scope = JSON.parse(scope || "{}") as Record<string, unknown[]>;
    } catch {
      setError(t("admin.dataScopeHint"));
      return;
    }
    try {
      if (project)
        await m.updateProject.mutateAsync({
          id: project.id,
          body: { name, group_name: group, description, data_scope, archived },
        });
      else await m.createProject.mutateAsync({ key, name, group_name: group, description, data_scope });
      toast.success(t("admin.saved"));
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };
  return (
    <Modal
      open
      title={project ? project.name : t("admin.newProject")}
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>{t("common.cancel")}</Button>
          <Button variant="primary" onClick={() => void save()} disabled={!name || !key}>
            {t("common.save")}
          </Button>
        </>
      }
    >
      {error && <ErrorBox>{error}</ErrorBox>}
      <div className={s.formGrid}>
        <Field label={t("admin.key")} hint="a-z, 0-9, _">
          <Input value={key} disabled={!!project} onChange={(e) => setKey(e.target.value)} mono />
        </Field>
        <Field label={t("common.name")}>
          <Input value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label={t("admin.group")} className={s.full}>
          <Input value={group} onChange={(e) => setGroup(e.target.value)} />
        </Field>
        <Field label={t("common.description")} className={s.full}>
          <Textarea value={description} onChange={(e) => setDescription(e.target.value)} />
        </Field>
        <Field label={t("admin.dataScope")} hint={t("admin.dataScopeHint")} className={s.full}>
          <Textarea value={scope} onChange={(e) => setScope(e.target.value)} mono />
        </Field>
        {project && <Switch checked={archived} onChange={setArchived} label="Archived" />}
      </div>
    </Modal>
  );
}
