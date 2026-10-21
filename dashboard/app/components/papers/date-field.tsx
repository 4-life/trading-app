import { Popover } from "@base-ui/react/popover";
import { CalendarIcon } from "lucide-react";
import { useState } from "react";

import { Calendar } from "@/components/ui/calendar";
import { FIELD_CLASS } from "@/lib/styles";

// A day as the form posts it (YYYY-MM-DD), from the local calendar day picked.
function toDay(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${String(date.getFullYear())}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

function fromDay(day: string): Date | undefined {
  const [y, m, d] = day.split("-").map(Number);
  return y && m && d ? new Date(y, m - 1, d) : undefined;
}

// A date picked on a calendar (a popover), posted as `name` = YYYY-MM-DD -
// empty until one is picked, or once cleared.
export function DateField({
  name,
  label,
  defaultValue,
  emptyText,
}: {
  name: string;
  label: string;
  defaultValue: string; // YYYY-MM-DD or ""
  emptyText: string; // shown with no date
}) {
  const [day, setDay] = useState(defaultValue);
  const [open, setOpen] = useState(false);
  const selected = fromDay(day);
  return (
    <div className="flex flex-col gap-0.5 text-xs text-muted-foreground">
      {label}
      <input type="hidden" name={name} value={day} />
      <div className="flex items-center gap-1">
        <Popover.Root open={open} onOpenChange={setOpen}>
          <Popover.Trigger className={`${FIELD_CLASS} flex w-40 items-center gap-1.5 text-left`}>
            <CalendarIcon className="size-3.5" />
            <span className={day ? "text-foreground" : undefined}>{day || emptyText}</span>
          </Popover.Trigger>
          <Popover.Portal>
            <Popover.Positioner sideOffset={4} className="z-[60]">
              <Popover.Popup className="rounded-lg border bg-background shadow-md">
                <Calendar
                  mode="single"
                  selected={selected}
                  defaultMonth={selected}
                  captionLayout="dropdown"
                  disabled={{ after: new Date() }}
                  onSelect={(date) => {
                    setDay(date ? toDay(date) : "");
                    setOpen(false);
                  }}
                />
              </Popover.Popup>
            </Popover.Positioner>
          </Popover.Portal>
        </Popover.Root>
        {day && (
          <button type="button" className="underline" onClick={() => setDay("")}>
            Clear
          </button>
        )}
      </div>
    </div>
  );
}
