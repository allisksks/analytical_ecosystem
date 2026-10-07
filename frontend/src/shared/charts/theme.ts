/** Reads design tokens so charts follow the light/dark theme exactly like the rest of the UI. */
export interface ChartTheme {
  palette: string[];
  ink: string;
  ink2: string;
  ink3: string;
  line: string;
  surface: string;
  brand: string;
  font: string;
}

export function readTheme(): ChartTheme {
  const cs = getComputedStyle(document.documentElement);
  const v = (name: string, fallback: string) => cs.getPropertyValue(name).trim() || fallback;
  return {
    palette: Array.from({ length: 8 }, (_, i) => v(`--chart-${i + 1}`, "#2a78d6")),
    ink: v("--ink", "#1f2a36"),
    ink2: v("--ink-2", "#4a5764"),
    ink3: v("--ink-3", "#66727e"),
    line: v("--line-soft", "#eceff4"),
    surface: v("--surface", "#ffffff"),
    brand: v("--brand", "#2a6be0"),
    font: v("--font", "sans-serif"),
  };
}
