import { useSearchParams } from "react-router";
import { useSources } from "./api";

export function useSelectedSource() {
  const sources = useSources();
  const [params, setParams] = useSearchParams();
  const id = params.get("source") ?? sources.data?.[0]?.id;
  const source = sources.data?.find((x) => x.id === id);
  const select = (sid: string) =>
    setParams((p) => {
      p.set("source", sid);
      p.delete("table");
      return p;
    });
  return { sources, source, select };
}
