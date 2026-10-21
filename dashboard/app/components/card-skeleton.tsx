import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

// A card's place while its data loads: its title and `rows` placeholder lines
// (or one `height` block, e.g. a chart).
export function CardSkeleton({
  title,
  rows = 3,
  height,
}: {
  title: string;
  rows?: number;
  height?: string; // a Tailwind height class
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {height ? (
          <Skeleton className={`w-full ${height}`} />
        ) : (
          Array.from({ length: rows }, (_, k) => <Skeleton key={k} className="h-5 w-full" />)
        )}
      </CardContent>
    </Card>
  );
}
