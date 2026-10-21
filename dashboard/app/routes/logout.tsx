import { redirect } from 'react-router';

import { api } from '@/lib/api';
import { getToken, sessionCookie } from '@/lib/session';

// Revokes the token at the API (POST /logout), then clears the cookie - signed
// out even if the API is down.
export async function action({ request }: { request: Request }) {
  if (await getToken(request)) {
    try {
      await api(request, '/logout', { method: 'POST' });
    } catch {
      // Already invalid (a 401 throws the redirect to /login): nothing to revoke.
    }
  }
  return redirect('/login', {
    headers: { 'Set-Cookie': await sessionCookie.serialize('', { maxAge: 0 }) },
  });
}
