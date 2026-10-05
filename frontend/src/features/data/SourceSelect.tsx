import { useI18n } from "../../shared/i18n";
import { Select } from "../../shared/ui";
import { useSelectedSource } from "./useSelectedSource";

export function SourceSelect() {
  const { t } = useI18n();
  const { sources, source, select } = useSelectedSource();
  return (
    <Select
      aria-label={t("data.pickSource")}
      value={source?.id ?? ""}
      onChange={(e) => select(e.target.value)}
      style={{ maxWidth: 360 }}
    >
      {sources.data?.map((x) => (
        <option key={x.id} value={x.id}>
          {x.name}
        </option>
      ))}
    </Select>
  );
}
