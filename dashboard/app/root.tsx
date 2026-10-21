import { useEffect } from "react";
import type { LinksFunction, MetaFunction } from "react-router";
import {
  Links,
  Meta,
  Outlet,
  Scripts,
  ScrollRestoration,
  isRouteErrorResponse,
  useLoaderData,
  useRouteError,
} from "react-router";

import { Toaster } from "@/components/ui/toast";
import { reportReachable } from "@/lib/unreachable";

import styles from "./app.css?url";
import { checkBackendHealth } from "./lib/backend";
import { APP_TITLE } from "./lib/page-title";

export const links: LinksFunction = () => [{ rel: "stylesheet", href: styles }];

// Default title; the home route replaces it with the PnL title.
export const meta: MetaFunction = () => [{ title: APP_TITLE }];

// Not waited for: the page renders at once; an unhealthy API is a toast.
export function loader() {
  return { health: checkBackendHealth() };
}

type RootData = ReturnType<typeof loader>;
let lastData: RootData | null = null;

// A refresh that can't reach the dashboard server keeps the last data (the
// home route's toast says so) instead of the error page.
export async function clientLoader({
  serverLoader,
}: {
  serverLoader: () => Promise<RootData>;
}): Promise<RootData> {
  try {
    lastData = await serverLoader();
    return lastData;
  } catch (error) {
    if (lastData === null) {
      throw error;
    }
    return lastData;
  }
}

export function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <head>
        <meta charSet="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <Meta />
        <Links />
      </head>
      <body className="bg-background text-foreground">
        {children}
        <ScrollRestoration />
        <Scripts />
      </body>
    </html>
  );
}

export default function App() {
  const data = useLoaderData<typeof clientLoader>();
  useEffect(() => {
    lastData = data;
    let current = true;
    void data.health.then((h) => {
      if (current) {
        reportReachable("api", "api status", h.healthy, "API unreachable");
      }
    });
    return () => {
      current = false;
    };
  }, [data]);

  return (
    <Toaster>
      <Outlet />
    </Toaster>
  );
}

// Shown instead of the page when it can't load - e.g. the browser can't reach
// the dashboard server ("Failed to fetch" while it's restarting).
export function ErrorBoundary() {
  const error = useRouteError();
  const unreachable = error instanceof TypeError && /fetch/i.test(error.message);
  return (
    <main className="flex min-h-screen flex-col items-center justify-center p-4 text-center">
      <p className="text-lg text-muted-foreground">
        {unreachable ? "Server unavailable" : "Something went wrong"}
      </p>
      {!unreachable && <p className="mt-2 text-sm text-muted-foreground">{errorDetail(error)}</p>}
    </main>
  );
}

function errorDetail(error: unknown): string {
  if (isRouteErrorResponse(error)) return `${error.status} ${error.statusText}`;
  return error instanceof Error ? error.message : String(error);
}
