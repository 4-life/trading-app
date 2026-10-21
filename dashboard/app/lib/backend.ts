const API_URL = process.env.API_URL ?? "http://api:8000";

// Public endpoint - no login needed.
export async function checkBackendHealth(): Promise<{ healthy: boolean }> {
  try {
    const response = await fetch(`${API_URL}/health`, { signal: AbortSignal.timeout(3000) });
    if (!response.ok) return { healthy: false };
    const body = (await response.json()) as { status?: string };
    return { healthy: body.status === "ok" };
  } catch {
    return { healthy: false };
  }
}
