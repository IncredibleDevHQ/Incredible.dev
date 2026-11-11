// The brand a channel's work wears: the chip in its header and the menu that changes it, and the
// picker an empty channel's start shows.
import { Check, Globe, Palette } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api, type Channel } from "../api";
import { useHouse } from "../store";
import { Select } from "./Select";

// The picker's last row, which reads a brand from a website rather than wearing one.
const READ = "read-a-website";
const host = (url: string) => url.replace(/^https?:\/\//, "").split("/")[0];

async function wear(channelId: string, slug: string) {
  try {
    await api.wearBrand(channelId, slug);
    await useHouse.getState().loadBrands();
  } catch (error) {
    useHouse.getState().say((error as Error).message);
  }
}

// Each brand with its logo and where it came from, opening as the pointer rests on it.
export function BrandSelect({ channel }: { channel: Channel }) {
  const brands = useHouse((s) => s.brands);
  const readBrandFor = useHouse((s) => s.readBrandFor);
  const options = [
    ...brands.map((b) => ({
      value: b.slug,
      label: b.name,
      description: b.slug === "default" ? "The house default" : b.source ? `From ${host(b.source)}` : "A brand pack",
      icon: b.logo ? <img src={b.logo} alt="" /> : <Palette />,
    })),
    { value: READ, label: "Read one from a website", description: "Its colours, type and logo", icon: <Globe /> },
  ];
  return (
    <Select
      className="brand-select"
      size="sm"
      openOnHover
      aria-label={`The brand #${channel.name} wears`}
      value={channel.brand || "default"}
      options={options}
      onChange={(value) => (value === READ ? readBrandFor(channel.id) : void wear(channel.id, value))}
    />
  );
}

export function ChannelBrand({ channel }: { channel: Channel }) {
  const brands = useHouse((s) => s.brands);
  const loadBrands = useHouse((s) => s.loadBrands);
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  useEffect(() => {
    if (!brands.length) void loadBrands().catch(() => undefined);
  }, [brands.length, loadBrands]);
  const worn = brands.find((b) => b.slug === (channel.brand || "default"));
  return (
    <>
      <button
        type="button"
        className="chip brand-chip"
        aria-expanded={Boolean(anchor)}
        title={`Everything made in #${channel.name} wears ${worn?.name ?? "the house brand"}. Click to change it.`}
        onClick={(e) => setAnchor(anchor ? null : e.currentTarget)}
      >
        {worn?.logo ? <img src={worn.logo} alt="" /> : <Palette />}
        {worn?.name ?? "Brand"}
      </button>
      {anchor && <BrandMenu channel={channel} anchor={anchor} onClose={() => setAnchor(null)} />}
    </>
  );
}

export function BrandMenu({ channel, anchor, onClose }: { channel: Channel; anchor: HTMLElement; onClose: () => void }) {
  const brands = useHouse((s) => s.brands);
  const readBrandFor = useHouse((s) => s.readBrandFor);
  const box = useRef<HTMLDivElement>(null);
  const [place, setPlace] = useState<{ top: number; left: number } | null>(null);
  useLayoutEffect(() => {
    const r = anchor.getBoundingClientRect();
    setPlace({ top: r.bottom + 6, left: Math.max(12, Math.min(window.innerWidth - 300, r.left)) });
  }, [anchor]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    const onDown = (e: PointerEvent) => {
      if (!box.current?.contains(e.target as Node) && !anchor.contains(e.target as Node)) onClose();
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("pointerdown", onDown);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("pointerdown", onDown);
    };
  }, [anchor, onClose]);
  const pick = async (slug: string) => {
    await wear(channel.id, slug);
    onClose();
  };
  return createPortal(
    <div className="pop brand-menu" ref={box} role="dialog" aria-label={`The brand #${channel.name} wears`} style={place ? place : { visibility: "hidden", top: 0, left: 0 }}>
      <h3>#{channel.name} wears</h3>
      <div className="pop-list" role="radiogroup">
        {brands.map((b) => (
          <button type="button" role="radio" key={b.slug} aria-checked={(channel.brand || "default") === b.slug} onClick={() => void pick(b.slug)}>
            {(channel.brand || "default") === b.slug ? <Check size={16} /> : <Palette size={16} />}
            <span>
              <b>{b.name}</b>
              <small>{b.source ? `From ${host(b.source)}` : "The configured pack"}</small>
            </span>
          </button>
        ))}
        <button
          type="button"
          onClick={() => {
            onClose();
            readBrandFor(channel.id);
          }}
        >
          <Globe size={16} />
          <span>
            <b>Read one from a website</b>
          </span>
        </button>
      </div>
    </div>,
    document.body,
  );
}
