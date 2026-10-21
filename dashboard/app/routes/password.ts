import { data } from "react-router";

import { api } from "@/lib/api";
import { sessionCookie } from "@/lib/session";

// Changes the app password (POST /password, docs/api.md#authentication): the
// API logs every session out and returns this one a new token - kept in the
// session cookie, so the owner stays signed in.
export async function action({ request }: { request: Request }) {
  const form = await request.formData();
  const next = String(form.get("new_password") ?? "");
  if (next !== String(form.get("confirm_password") ?? "")) {
    return { error: "the new passwords don't match" };
  }
  const result = await api<{ token: string }>(request, "/password", {
    method: "POST",
    body: { current_password: String(form.get("current_password") ?? ""), new_password: next },
  });
  if (!result.ok) {
    return { error: result.error };
  }
  return data(
    { saved: true },
    { headers: { "Set-Cookie": await sessionCookie.serialize(result.data.token) } },
  );
}
