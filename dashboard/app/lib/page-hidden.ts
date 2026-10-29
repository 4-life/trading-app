// When the page was last hidden. A mobile browser freezes a background tab
// (another app, the screen off): its requests in flight are cut off then -
// not the API or the server failing.
let lastHidden = 0;
if (typeof document !== "undefined") {
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      lastHidden = Date.now();
    }
  });
}

// The page is hidden, or was since `since` (a Date.now()).
export function hiddenSince(since: number): boolean {
  return document.hidden || lastHidden >= since;
}
