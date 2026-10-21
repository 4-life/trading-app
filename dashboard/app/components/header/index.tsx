import { Settings as SettingsIcon } from "lucide-react";
import type { ReactNode } from "react";
import { Form } from "react-router";

import { Button } from "@/components/ui/button";

import { UtcClock } from "./utc-clock";

// Title, system health, UTC clock, settings button, log out
// (docs/dashboard.md#header).
export function Header({
  health,
  onOpenSettings,
}: {
  health: ReactNode;
  onOpenSettings: () => void;
}) {
  return (
    <header className="flex flex-wrap items-center justify-between gap-2">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <h1 className="text-2xl font-semibold">Trading App</h1>
        {health}
      </div>
      <div className="flex items-center gap-2">
        <UtcClock />
        <Button variant="outline" size="sm" onClick={onOpenSettings}>
          <SettingsIcon /> Settings
        </Button>
        <Form method="post" action="/logout">
          <Button type="submit" variant="ghost" size="sm">
            Log out
          </Button>
        </Form>
      </div>
    </header>
  );
}
