// The page's footer (docs/dashboard.md#footer).
export function Footer() {
  return (
    <footer className="border-t pt-4 text-xs text-muted-foreground">
      {`Trading App · © ${String(new Date().getUTCFullYear())}`}
    </footer>
  );
}
