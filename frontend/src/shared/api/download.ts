import { API_BASE, ApiError, authFetch } from "./client";

/** POSTs JSON to an endpoint that returns a file and triggers the browser download. */
export async function downloadPost(path: string, body: unknown, filename: string): Promise<void> {
  await save(
    new Request(`${API_BASE}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
    filename,
  );
}

/** GETs a file (with the access token) and triggers the browser download. */
export async function downloadGet(path: string, filename: string): Promise<void> {
  await save(new Request(`${API_BASE}${path}`), filename);
}

async function save(req: Request, filename: string): Promise<void> {
  const res = await authFetch(req);
  if (!res.ok) {
    let problem = {};
    try {
      problem = await res.json();
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, problem);
  }
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
