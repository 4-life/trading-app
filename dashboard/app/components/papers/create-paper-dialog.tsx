import { useCallback, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";

import { CreatePaperForm } from "./create-paper-form";

// The create-paper form in a dialog - closed once the paper is created; an
// error keeps it open, shown in it (docs/dashboard.md#papers).
export function CreatePaperDialog({ assets }: { assets: string[] }) {
  const [open, setOpen] = useState(false);
  // Stable, so the form's effect doesn't re-run (and close it) on a re-render.
  const close = useCallback(() => setOpen(false), []);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={<Button size="sm" />}>New paper</DialogTrigger>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>New paper</DialogTitle>
          <DialogDescription>
            Starts in demo and disabled - enable it once it's prepared.
          </DialogDescription>
        </DialogHeader>
        <CreatePaperForm assets={assets} onCreated={close} />
      </DialogContent>
    </Dialog>
  );
}
