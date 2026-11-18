// The time now, and a live time that counts up from a moment, said as a duration is ("49s",
// "1m 04s") so it reads the same as the times of what is done. Written for this house from notes
// on how agent-progress components behave; no other component's source is in it.
import { useEffect, useState } from "react";
import { took } from "./format";

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

// How long since `since` (seconds since the epoch), counting up. Screen readers are told the time
// where it matters by the row around it, not every second.
export function Clock({ since }: { since: number }) {
  const now = useNow(true);
  return (
    <time className="ag-clock" aria-hidden="true">
      {took(Math.max(0, now - since))}
    </time>
  );
}
