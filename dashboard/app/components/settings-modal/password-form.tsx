import { useEffect, useRef } from "react";
import { useFetcher } from "react-router";

import { Button } from "@/components/ui/button";
import { FIELD_CLASS } from "@/lib/styles";

const FIELDS = [
  ["current_password", "Current password", "current-password"],
  ["new_password", "New password (8+ characters)", "new-password"],
  ["confirm_password", "Repeat the new password", "new-password"],
] as const;

// The app password (routes/password.ts): every other session is logged out.
export function PasswordForm() {
  const fetcher = useFetcher<{ error?: string; saved?: boolean }>();
  const form = useRef<HTMLFormElement>(null);
  const saved = fetcher.state === "idle" && fetcher.data?.saved === true;

  useEffect(() => {
    if (saved) {
      form.current?.reset();
    }
  }, [saved]);

  return (
    <fetcher.Form ref={form} method="post" action="/password" className="space-y-3">
      <p className="text-sm font-medium">App password</p>
      {FIELDS.map(([name, label, autoComplete]) => (
        <label key={name} className="flex flex-col gap-1 text-sm">
          {label}
          <input
            name={name}
            type="password"
            required
            minLength={name === "current_password" ? undefined : 8}
            autoComplete={autoComplete}
            className={FIELD_CLASS}
          />
        </label>
      ))}
      {fetcher.data?.error && <p className="text-sm text-destructive">{fetcher.data.error}</p>}
      {saved && <p className="text-sm text-green-500">Password changed - other sessions logged out</p>}
      <Button type="submit" disabled={fetcher.state !== "idle"}>
        Change password
      </Button>
    </fetcher.Form>
  );
}
