import { Button } from "@/components/ui/button";

export function FilterButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: string;
}) {
  return (
    <Button variant={active ? "secondary" : "ghost"} size="xs" onClick={onClick}>
      {children}
    </Button>
  );
}
