import { createCookie } from 'react-router';

// Holds the API login token (docs/api.md#authentication). HTTP-only, so the
// browser's JavaScript never sees it; only the dashboard server reads it.
export const sessionCookie = createCookie('session', {
  httpOnly: true,
  sameSite: 'lax',
  // HTTPS only in production (browsers accept it on http://localhost too).
  secure: process.env.NODE_ENV === 'production',
  path: '/',
  maxAge: 7 * 24 * 3600,
});

export async function getToken(request: Request): Promise<string | null> {
  const token: unknown = await sessionCookie.parse(request.headers.get('Cookie'));
  return typeof token === 'string' && token ? token : null;
}
