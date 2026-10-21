import { toast } from "@/components/ui/toast";

// One toast per group ("api", "server") while any of its parts can't be
// reached, naming them - closed once they all answer again. The page keeps
// its last data.
// The toasts go out after the current effects: on the first render the parts
// report before the Toaster (their parent) subscribes, which would lose them.
const failing = new Map<string, Set<string>>();
const open = new Map<string, string>();
let nextId = 0;

function description(parts: Set<string>): string {
  return `Not loaded: ${[...parts].sort().join(", ")}. Showing the last data.`;
}

export function reportReachable(group: string, part: string, ok: boolean, title: string) {
  const parts = failing.get(group) ?? new Set<string>();
  failing.set(group, parts);
  const changed = ok ? parts.delete(part) : !parts.has(part) && Boolean(parts.add(part));
  const id = open.get(group);
  if (parts.size === 0) {
    if (id !== undefined) {
      setTimeout(() => toast.close(id));
      open.delete(group);
    }
    return;
  }
  const text = description(parts);
  if (id === undefined) {
    const newId = `unreachable-${group}-${String(nextId++)}`;
    open.set(group, newId);
    setTimeout(() => {
      toast.add({ id: newId, title, description: text, type: "warning", timeout: 0 });
    });
  } else if (changed) {
    setTimeout(() => toast.update(id, { description: text }));
  }
}
