// A loading region has one accessible name; its visual placeholders stay out of the tab order.
export function Skeleton({ label, shape = "lines" }: {
  label: string;
  shape?: "lines" | "form" | "chart" | "cards" | "inline";
}) {
  return <span role="status" aria-label={label} aria-busy="true" className={`skeleton sk-${shape}`}>
    <i aria-hidden="true" /><i aria-hidden="true" /><i aria-hidden="true" />
  </span>;
}
