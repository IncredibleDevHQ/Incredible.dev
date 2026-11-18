// Times and names as the agent components say them. Written for this house from notes on how
// agent-progress components behave; no other component's source is in it.

// How long something took: "<1s", "12s", "4m 08s", "1h 02m". Nothing for a time not known.
export function took(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return "";
  if (seconds < 1) return "<1s";
  const whole = Math.round(seconds);
  if (whole < 60) return `${whole}s`;
  const minutes = Math.floor(whole / 60);
  const rest = whole % 60;
  if (minutes < 60) return rest ? `${minutes}m ${String(rest).padStart(2, "0")}s` : `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  const left = minutes % 60;
  return left ? `${hours}h ${String(left).padStart(2, "0")}m` : `${hours}h`;
}

// A running clock: "0:07", "9:47", "1:02:05".
export function clock(seconds: number): string {
  const whole = Math.max(0, Math.floor(Number.isFinite(seconds) ? seconds : 0));
  const hours = Math.floor(whole / 3600);
  const minutes = Math.floor((whole % 3600) / 60);
  const rest = String(whole % 60).padStart(2, "0");
  return hours ? `${hours}:${String(minutes).padStart(2, "0")}:${rest}` : `${minutes}:${rest}`;
}

// A long path or name kept to `max` characters by cutting its middle: its end (a file's own name)
// is what tells one from another, so the end keeps the larger share.
export function middle(text: string, max = 44): string {
  if (text.length <= max) return text;
  const tail = Math.ceil((max - 1) * 0.6);
  return `${text.slice(0, max - 1 - tail)}…${text.slice(text.length - tail)}`;
}
