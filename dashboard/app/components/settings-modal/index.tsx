import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { Settings } from "@/types/settings";

import { ExchangeApiSection } from "./exchange-api";
import { PasswordForm } from "./password-form";
import { SettingsForm } from "./settings-form";

// The exchange API, integration keys and the app password (docs/dashboard.md#settings).
export function SettingsModal({
  settings,
  error,
  open,
  onOpenChange,
}: {
  settings: Settings | null;
  error: string | null; // why GET /settings failed
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Settings</DialogTitle>
          <DialogDescription>
            Keys are stored encrypted. Leave a field empty to keep its stored value.
          </DialogDescription>
        </DialogHeader>
        {settings === null ? (
          <p className="text-sm text-destructive">Settings unavailable: {error ?? "unknown error"}</p>
        ) : (
          <div className="space-y-6">
            <ExchangeApiSection api={settings.exchange_api} />
            <SettingsForm settings={settings} />
            <PasswordForm />
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
