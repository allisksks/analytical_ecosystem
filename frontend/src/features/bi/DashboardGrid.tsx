import { useMemo } from "react";
import ReactGridLayout, { useContainerWidth, type Layout } from "react-grid-layout";
import "react-grid-layout/css/styles.css";
import type { Dashboard, WidgetOut } from "../../shared/api/types";
import { useToast } from "../../shared/ui";
import { useBiMutations, type GlobalFilters } from "./api";
import { WidgetCard } from "./WidgetCard";
import s from "./bi.module.css";

const ROW_HEIGHT = 72;

export function DashboardGrid({
  dashboard,
  filters,
  editing,
  onConfigure,
  publicToken,
}: {
  dashboard: Dashboard;
  filters: GlobalFilters;
  editing: boolean;
  onConfigure?: (w: WidgetOut) => void;
  publicToken?: string;
}) {
  const toast = useToast();
  const m = useBiMutations();
  const { width, containerRef, mounted } = useContainerWidth();
  const narrow = width < 760;
  const layout = useMemo<Layout>(
    () =>
      dashboard.widgets.map((w, i) => {
        const l = w.layout as { x?: number; y?: number; w?: number; h?: number };
        return narrow
          ? { i: w.id, x: 0, y: i * 4, w: 12, h: l.h ?? 4 }
          : { i: w.id, x: l.x ?? 0, y: l.y ?? i * 4, w: l.w ?? 6, h: l.h ?? 4, minW: 2, minH: 2 };
      }),
    [dashboard.widgets, narrow],
  );
  const save = (next: Layout) => {
    if (!editing || narrow) return;
    const changed = next.some((n) => {
      const cur = layout.find((l) => l.i === n.i);
      return !cur || cur.x !== n.x || cur.y !== n.y || cur.w !== n.w || cur.h !== n.h;
    });
    if (!changed) return;
    m.saveLayout.mutate(
      { dashId: dashboard.id, body: next.map((n) => ({ id: n.i, layout: { x: n.x, y: n.y, w: n.w, h: n.h } })) },
      { onError: (e) => toast.error(e.message) },
    );
  };
  return (
    <div ref={containerRef} className={s.grid}>
      {mounted && (
        <ReactGridLayout
          width={width}
          layout={layout}
          gridConfig={{ cols: 12, rowHeight: ROW_HEIGHT, margin: [16, 16], containerPadding: [0, 0] }}
          dragConfig={{ enabled: editing && !narrow, handle: ".drag-handle" }}
          resizeConfig={{ enabled: editing && !narrow }}
          onLayoutChange={save}
        >
          {dashboard.widgets.map((w) => (
            <div key={w.id}>
              <WidgetCard
                widget={w}
                dashId={dashboard.id}
                filters={filters}
                editing={editing}
                canEdit={dashboard.can_edit && !publicToken}
                onConfigure={() => onConfigure?.(w)}
                publicToken={publicToken}
              />
            </div>
          ))}
        </ReactGridLayout>
      )}
    </div>
  );
}
