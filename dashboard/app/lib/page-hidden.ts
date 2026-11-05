// When the page was last hidden. A mobile browser freezes a background tab
// (another app, the screen off): its requests in flight are cut off then -
// not the API or the server failing.
let lastHidden = 0;
// When it was last shown again: the phone's network takes a while to wake up.
let lastShown = 0;
if (typeof document !== "undefined") {
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      lastHidden = Date.now();
    } else {
      lastShown = Date.now();
    }
  });
}

// The page is hidden, or was since `since` (a Date.now()).
export function hiddenSince(since: number): boolean {
  return document.hidden || lastHidden >= since;
}

// The page was shown again within the last `ms`.
export function shownWithin(ms: number): boolean {
  return Date.now() - lastShown < ms;
}
