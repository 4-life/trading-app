import { redirect } from 'react-router';

import { getToken } from '@/lib/session';

// Server-side only: API_URL is a Docker-internal hostname the browser can't
// reach. Every call forwards the login token and the visitor's IP (used by
// the API's login rate limit).
const API_URL = process.env.API_URL ?? 'http://api:8000';
const TIMEOUT_MS = 5000;

export type ApiResult<T> =
  | { ok: true; data: T }
  | { ok: false; status: number; error: string };

// Nginx sets X-Real-IP to the connecting address, overwriting any sent by
// the client; it *appends* that address to X-Forwarded-For, so only the last
// entry there is real - the first ones are whatever the client sent.
function clientIp(request: Request): string | null {
  const real = request.headers.get('x-real-ip');
  if (real) return real.trim();
  const forwarded = request.headers.get('x-forwarded-for');
  return forwarded ? (forwarded.split(',').at(-1)?.trim() ?? null) : null;
}

export async function api<T>(
  request: Request,
  path: string,
  init: { method?: string; body?: unknown; auth?: boolean; timeoutMs?: number } = {},
): Promise<ApiResult<T>> {
  const headers: Record<string, string> = {};
  const ip = clientIp(request);
  if (ip) headers['X-Forwarded-For'] = ip;
  if (init.body !== undefined) headers['Content-Type'] = 'application/json';
  if (init.auth !== false) {
    const token = await getToken(request);
    if (!token) throw redirect('/login');
    headers.Authorization = `Bearer ${token}`;
  }

  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      method: init.method ?? 'GET',
      headers,
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
      signal: AbortSignal.timeout(init.timeoutMs ?? TIMEOUT_MS),
    });
  } catch {
    return { ok: false, status: 0, error: 'API unreachable' };
  }

  if (response.status === 401 && init.auth !== false) throw redirect('/login');
  if (response.status === 204) return { ok: true, data: undefined as T };
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const detail =
      body && typeof body === 'object' && 'detail' in body ? body.detail : null;
    return { ok: false, status: response.status, error: errorText(detail, response.status) };
  }
  return { ok: true, data: body as T };
}

// FastAPI's error detail: a message, or for invalid fields a list of
// { loc: ["body", "<field>"], msg } - shown as "<field>: <msg>".
function errorText(detail: unknown, status: number): string {
  if (typeof detail === 'string') {
    return detail;
  }
  if (Array.isArray(detail)) {
    const parts = detail.map((d: unknown) => {
      if (!d || typeof d !== 'object') {
        return String(d);
      }
      const { loc, msg } = d as { loc?: unknown; msg?: unknown };
      const field = Array.isArray(loc) ? loc.filter((x) => x !== 'body').join('.') : '';
      return field ? `${field}: ${String(msg)}` : String(msg);
    });
    if (parts.length > 0) {
      return parts.join('; ');
    }
  }
  return `HTTP ${String(status)}`;
}

// A page section's data: what the API answered, or that it couldn't be
// reached - the section then keeps its last data (components/section.tsx);
// `login`: the login expired - the page goes to /login.
export type Loaded<T> = { ok: true; data: T } | { ok: false; login?: boolean };

export async function load<T>(
  request: Request,
  path: string,
  timeoutMs?: number,
): Promise<Loaded<T>> {
  try {
    const result = await api<T>(request, path, { timeoutMs });
    return result.ok ? { ok: true, data: result.data } : { ok: false };
  } catch (error) {
    // api() throws a redirect to /login - streamed, it can't redirect itself.
    if (error instanceof Response) {
      return { ok: false, login: true };
    }
    throw error;
  }
}
