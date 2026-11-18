// The time now, and a clock that counts up from a moment. Written for this house from notes on
// how agent-progress components behave; no other component's source is in it.
import { useEffect, useState } from "react";
import { clock } from "./format";

// Seconds since the epoch, ticking once a second while `live` (a clock that is not shown costs
// nothing).
export function useNow(live = true): number {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    if (!live) return;
    setNow(Date.now() / 1000);
    const tick = window.setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => window.clearInterval(tick);
  }, [live]);
  return now;
}

// A clock counting up from `since` (seconds since the epoch). Screen readers are told the time
// where it matters by the row around it, not every second.
export function Clock({ since }: { since: number }) {
  const now = useNow(true);
  return (
    <time className="ag-clock" aria-hidden="true">
      {clock(now - since)}
    </time>
  );
}
