import { PassThrough } from "node:stream";
import { createReadableStreamFromReadable } from "@react-router/node";
import type { EntryContext, RouterContextProvider } from "react-router";
import { ServerRouter } from "react-router";
import { renderToPipeableStream } from "react-dom/server";

// How long the streamed loader data may take - pending promises are rejected
// after it ("Unexpected Server Error"). Above the slowest load (the chart's 20 s).
export const streamTimeout = 30_000;

// On every page and data response: no framing (clickjacking), no MIME
// sniffing, no URLs leaked to other sites. (HSTS is the HTTPS proxy's.)
const SECURITY_HEADERS: Record<string, string> = {
  "Content-Security-Policy": "frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'",
  "X-Frame-Options": "DENY",
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "same-origin",
};

function secure(headers: Headers): Headers {
  for (const [name, value] of Object.entries(SECURITY_HEADERS)) {
    headers.set(name, value);
  }
  return headers;
}

export function handleDataRequest(response: Response): Response {
  secure(response.headers);
  return response;
}

export default function handleRequest(
  request: Request,
  responseStatusCode: number,
  responseHeaders: Headers,
  routerContext: EntryContext,
  _loadContext: RouterContextProvider,
) {
  return new Promise((resolve, reject) => {
    let shellRendered = false;
    const { pipe, abort } = renderToPipeableStream(
      <ServerRouter context={routerContext} url={request.url} />,
      {
        onShellReady() {
          shellRendered = true;
          const body = new PassThrough();
          const stream = createReadableStreamFromReadable(body);

          responseHeaders.set("Content-Type", "text/html");
          secure(responseHeaders);

          resolve(
            new Response(stream, {
              headers: responseHeaders,
              status: responseStatusCode,
            }),
          );

          pipe(body);
        },
        onShellError(error: unknown) {
          reject(error);
        },
        onError(error: unknown) {
          responseStatusCode = 500;
          if (shellRendered) {
            console.error(error);
          }
        },
      },
    );

    setTimeout(abort, streamTimeout + 1000);
  });
}
