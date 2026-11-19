// Adjacent start times and durations are rounded independently in the saved clock.
// A boundary belongs to the beat that starts there.
export function spanAt<T extends {start: number}>(spans: T[], time: number): T | undefined {
  for (let index = spans.length - 1; index >= 0; index--) {
    if (time >= spans[index].start) return spans[index];
  }
  return spans[0];
}
