import { type ReactElement, type ReactNode, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";

// Confirmation before an action. `trigger` is the element that opens it
// (e.g. <Button size="xs" />), rendered with `children` inside;
// `alternative`, another way to go ahead, next to the confirm button.
export function ConfirmDialog({
  trigger,
  children,
  title,
  description,
  confirmLabel,
  destructive = false,
  onConfirm,
  alternative,
}: {
  trigger: ReactElement;
  children: ReactNode;
  title: string;
  description: ReactNode;
  confirmLabel: string;
  destructive?: boolean;
  onConfirm: () => void;
  alternative?: { label: string; onConfirm: () => void };
}) {
  const [open, setOpen] = useState(false);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={trigger}>{children}</DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <DialogClose render={<Button variant="outline" />}>Cancel</DialogClose>
          {alternative && (
            <Button
              variant="outline"
              onClick={() => {
                alternative.onConfirm();
                setOpen(false);
              }}
            >
              {alternative.label}
            </Button>
          )}
          <Button
            variant={destructive ? "destructive" : "default"}
            onClick={() => {
              onConfirm();
              setOpen(false);
            }}
          >
            {confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
