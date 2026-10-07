export function linkHref(kind: string, ref: string): string {
  switch (kind) {
    case "event":
      return `/ems?event=${encodeURIComponent(ref)}`;
    case "metric":
      return `/data/metrics?key=${encodeURIComponent(ref)}`;
    case "dashboard":
      return `/bi/dashboards?d=${encodeURIComponent(ref)}`;
    case "experiment":
      return `/ab/${encodeURIComponent(ref)}`;
    case "kb":
      return `/kb/${encodeURIComponent(ref)}`;
    default:
      return /^https?:\/\//.test(ref) ? ref : "#";
  }
}
