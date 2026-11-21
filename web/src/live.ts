// The server's live events (/api/stream), applied to the store as they arrive. The house pings a
// quiet stream every 15 seconds (PING_SECONDS in app.py), so a page that hears nothing for longer
// than HEARD_WITHIN has lost it: the house stopped, or the connection died without saying so.
// The store then says since when (`cut`), so nothing on the page blames an agent for a silence
// that is the page's own, and a stream that went quiet is opened again. A dropped connection
// reconnects on its own; once the house is heard from again the current views are read again,
// since events sent while it was away are gone.
import { useHouse, type LiveEvent } from "./store";

// Two pings missed, with room to spare.
const HEARD_WITHIN = 40_000;
const CHECK_EVERY = 5_000;

export function connectLive(): () => void {
  let source: EventSource | null = null;
  let closed = false;
  let wasOpen = false;
  let heard = Date.now();

  const lost = () => {
    if (useHouse.getState().cut === null) useHouse.setState({ cut: heard / 1000 });
  };
  const back = () => {
    heard = Date.now();
    if (useHouse.getState().cut !== null) useHouse.setState({ cut: null });
  };

  const open = () => {
    source = new EventSource("/api/stream");
    source.onopen = () => {
      back();
      const state = useHouse.getState();
      if (wasOpen && state.channelId) {
        void state.openChannel(state.channelId);
        if (state.threadId) void state.openThread(state.threadId);
      }
      wasOpen = true;
    };
    source.onmessage = (message) => {
      back();
      try {
        const event = JSON.parse(message.data) as LiveEvent;
        if (event.type !== "ping") useHouse.getState().apply(event);
      } catch {
        /* a malformed event is skipped */
      }
    };
    source.onerror = () => {
      if (closed) return;
      lost();
      if (useHouse.getState().session?.authenticated) {
        void fetch("/api/auth/session", {credentials: "same-origin"}).then(response => {
          if (!closed && response.status === 401) window.dispatchEvent(new Event("incredible:signout"));
        }).catch(() => undefined);
      }
    };
  };
  open();
  const watch = window.setInterval(() => {
    if (closed || Date.now() - heard < HEARD_WITHIN) return;
    lost();
    source?.close();
    open();
  }, CHECK_EVERY);
  return () => {
    closed = true;
    window.clearInterval(watch);
    source?.close();
  };
}
