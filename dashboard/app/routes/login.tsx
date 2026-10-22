import { Form, redirect, useActionData, useNavigation } from 'react-router';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { api } from '@/lib/api';
import { getToken, sessionCookie } from '@/lib/session';

export async function loader({ request }: { request: Request }) {
  if (await getToken(request)) throw redirect('/');
  return null;
}

export async function action({ request }: { request: Request }) {
  const form = await request.formData();
  const result = await api<{ token: string }>(request, '/login', {
    method: 'POST',
    body: { password: String(form.get('password') ?? '') },
    auth: false,
  });
  if (!result.ok) return { error: result.error };
  return redirect('/', {
    headers: { 'Set-Cookie': await sessionCookie.serialize(result.data.token) },
  });
}

export default function Login() {
  const data = useActionData<typeof action>();
  const submitting = useNavigation().state !== 'idle';
  return (
    <main className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>Trading App</CardTitle>
        </CardHeader>
        <CardContent>
          <Form method="post" className="space-y-3">
            <input
              type="password"
              name="password"
              placeholder="Password"
              autoFocus
              required
              className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm max-sm:h-11 max-sm:text-base"
            />
            {data?.error && <p className="text-sm text-destructive">{data.error}</p>}
            <Button type="submit" className="w-full" disabled={submitting}>
              {submitting ? 'Signing in…' : 'Sign in'}
            </Button>
          </Form>
        </CardContent>
      </Card>
    </main>
  );
}
