// Reading a brand from a website, on a page of its own: the address, then the read as it goes
// (each step ticks as the capture reaches it). While it reads, the read is all there is; once it's
// read, the brand's own page on Brands takes over. A read that stops says in which step, and why,
// and the address comes back to try again.
import { ArrowLeft } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { ProgressTracker } from "../components/ProgressTracker";
import { TextField } from "../components/TextField";
import { useHouse } from "../store";

const STEPS = [
  { id: "open", label: "Opening the site" },
  { id: "colours", label: "Taking its colours" },
  { id: "type", label: "Finding its type" },
  { id: "logo", label: "Finding its logo" },
  { id: "pack", label: "Writing the brand pack" },
];
const host = (url: string) => url.replace(/^https?:\/\//, "").split("/")[0];

export function ReadBrand() {
  const reads = useHouse((s) => s.reads);
  const channels = useHouse((s) => s.channels);
  const brandFor = useHouse((s) => s.brandFor);
  const openPage = useHouse((s) => s.openPage);
  const openBrand = useHouse((s) => s.openBrand);
  // The read this page follows: the one it starts, else one already under way.
  const [url, setUrl] = useState<string | null>(() => reads.find((r) => r.status === "reading")?.url ?? null);
  const [address, setAddress] = useState(() => (url ? url.replace(/^https?:\/\//, "") : ""));
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const read = reads.find((r) => r.url === url);
  const going = read?.status === "reading" || read?.status === "ready";
  // The channel that wears what it makes: the one a read under way was started for.
  const channel = channels.find((c) => c.id === (read ? read.channel : brandFor));

  // Once it's read, the brand's own page takes over, a beat after the last tick.
  const made = read?.status === "ready" ? read.slug : undefined;
  useEffect(() => {
    if (!made) return;
    const later = window.setTimeout(() => openBrand(made), 700);
    return () => window.clearTimeout(later);
  }, [made, openBrand]);

  const start = async (target: string) => {
    if (!target.trim() || busy) return;
    setBusy(true);
    setError("");
    try {
      const started = await api.readBrand(target.trim(), brandFor ?? "");
      // Followed from here on, never an older read of the same address (unless its news came first).
      useHouse.setState((s) => ({
        reads: s.reads.some((r) => r.url === started.url && r.status === "reading") ? s.reads : [started, ...s.reads.filter((r) => r.url !== started.url)],
      }));
      setUrl(started.url);
    } catch (failed) {
      setError((failed as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="page read-brand" aria-labelledby="read-brand-title">
      <button type="button" className="linkish read-back" onClick={() => openPage("brand")}>
        <ArrowLeft size={14} />
        Brands
      </button>
      <h1 id="read-brand-title">Create a brand from a website</h1>
      <p className="lede">
        Its first screen gives the colours, the type and the logo; a licensed font gets an open stand-in.
        {channel ? ` #${channel.name} wears it once it's made.` : ""}
      </p>
      {!going && (
        <form
          className="read-form"
          onSubmit={(e) => {
            e.preventDefault();
            void start(address);
          }}
        >
          <TextField
            aria-label="The website to read"
            prefix="https://"
            placeholder="yourcompany.com"
            hint="A homepage or a product page reads best."
            error={error || undefined}
            clearable
            autoFocus
            value={address}
            onChange={(e) => {
              // The field shows https:// already; a pasted address keeps the rest.
              setAddress(e.target.value.replace(/^https?:\/\//, ""));
              setError("");
            }}
          />
          <button type="submit" className="btn primary" disabled={!address.trim() || busy}>
            {busy ? "Starting…" : "Create brand"}
          </button>
        </form>
      )}
      {read && (
        <ProgressTracker
          className="read-steps"
          title={read.status === "ready" ? `${host(read.url)} is read` : read.status === "failed" ? `${host(read.url)} couldn't be read` : `Reading ${host(read.url)}`}
          steps={STEPS}
          current={read.status === "ready" ? "done" : (read.step ?? "open")}
          failed={read.status === "failed"}
        />
      )}
      {read?.status === "failed" && (
        <div className="read-failed" role="alert">
          <p>{read.message}</p>
          <p className="faint">Some sites turn automated reads away; their docs or a product page often reads instead.</p>
        </div>
      )}
    </section>
  );
}
