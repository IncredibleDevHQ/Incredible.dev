// The server's live events (/api/stream), applied to the store as they arrive. A dropped
// connection reconnects on its own; on reconnect the current views are read again, since events
// sent while it was down are gone.
import { useHouse, type LiveEvent } from "./store";

export function connectLive(): () => void {
  let source: EventSource | null = null;
  let closed = false;
  let wasOpen = false;

  const open = () => {
    source = new EventSource("/api/stream");
    source.onopen = () => {
      const state = useHouse.getState();
      if (wasOpen && state.channelId) {
        void state.openChannel(state.channelId);
        if (state.threadId) void state.openThread(state.threadId);
      }
      wasOpen = true;
    };
    source.onmessage = (message) => {
      try {
        useHouse.getState().apply(JSON.parse(message.data) as LiveEvent);
      } catch {
        /* a malformed event is skipped */
      }
    };
    source.onerror = () => {
      if (closed) source?.close();
      else if (useHouse.getState().session?.authenticated) {
        void fetch("/api/auth/session", {credentials: "same-origin"}).then(response => {
          if (response.status === 401) window.dispatchEvent(new Event("incredible:signout"));
        }).catch(() => undefined);
      }
    };
  };
  open();
  return () => {
    closed = true;
    source?.close();
  };
}
