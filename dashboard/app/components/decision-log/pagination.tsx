import { Link, useSearchParams } from "react-router";

// First / newer / older / last page links; keeps the current filters (?logPage=).
export function DecisionLogPagination({
  page,
  pageSize,
  total,
}: {
  page: number;
  pageSize: number;
  total: number;
}) {
  const [params] = useSearchParams();
  const pages = Math.max(1, Math.ceil(total / pageSize));
  if (pages <= 1) return null;

  const pageLink = (n: number) => {
    const next = new URLSearchParams(params);
    next.set("logPage", String(n));
    return `?${next.toString()}`;
  };

  return (
    <div className="flex items-center justify-end gap-2 text-sm">
      {page > 1 && (
        <>
          <Link to={pageLink(1)} preventScrollReset className="underline">
            « First
          </Link>
          <Link to={pageLink(page - 1)} preventScrollReset className="underline">
            ← Newer
          </Link>
        </>
      )}
      <span className="text-muted-foreground">
        Page {page} of {pages}
      </span>
      {page < pages && (
        <>
          <Link to={pageLink(page + 1)} preventScrollReset className="underline">
            Older →
          </Link>
          <Link to={pageLink(pages)} preventScrollReset className="underline">
            Last »
          </Link>
        </>
      )}
    </div>
  );
}
