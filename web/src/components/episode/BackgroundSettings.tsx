import { useState } from "react";
import { api, type BackgroundTexture, type EpisodeView } from "../../api";
import type { Run } from "./Ask";

type Props = { view: EpisodeView; run: Run; busy: boolean };

export function BackgroundSettings({ view, run, busy }: Props) {
  const savedColor = view.settings.background_color || "";
  const savedTexture = view.settings.background_texture || "solid";
  const [color, setColor] = useState(savedColor);
  const [texture, setTexture] = useState<BackgroundTexture>(savedTexture);
  const hex = color || view.background.brand_color;
  const valid = /^#[a-f0-9]{6}$/i.test(hex);
  const ground = valid ? hex : view.background.brand_color;
  const [image, size] = view.background.textures[texture];
  const names: Record<BackgroundTexture, string> = { solid: "Solid", dots: "Dots", grid: "Grid", diagonal: "Diagonal" };
  const rgb =
    ground
      .slice(1)
      .match(/../g)
      ?.map((n) => parseInt(n, 16)) || [];
  const light = rgb.length === 3 && rgb[0] * 0.21 + rgb[1] * 0.72 + rgb[2] * 0.07 > 128;
  return (
    <fieldset className="ep-background">
      <legend>Video background</legend>
      <div
        className="ep-background-sample"
        role="img"
        aria-label={`${names[texture]} background preview in ${ground}`}
        style={{
          backgroundColor: ground,
          backgroundImage: image,
          backgroundSize: size,
          color: light ? "#111" : "#fff",
        }}
      />
      <div className="ep-background-color">
        <label>
          Color{" "}
          <input aria-label="Background color" type="color" value={ground} onChange={(e) => setColor(e.target.value)} />
        </label>
        <input
          aria-label="Hex color"
          aria-invalid={!valid}
          type="text"
          value={hex}
          maxLength={7}
          spellCheck={false}
          onChange={(e) => setColor(e.target.value.toLowerCase())}
        />
      </div>
      <button type="button" className="linkish" disabled={!color} onClick={() => setColor("")}>
        Use brand color
      </button>
      <div className="ep-background-textures" role="group" aria-label="Background texture">
        {(Object.keys(names) as BackgroundTexture[]).map((t) => (
          <button type="button" key={t} aria-pressed={t === texture} className="btn" onClick={() => setTexture(t)}>
            {names[t]}
          </button>
        ))}
      </div>
      <button
        type="button"
        className="btn primary"
        disabled={!valid || busy || (savedColor === color && savedTexture === texture)}
        onClick={() => void run(() => api.chooseEpisode(view.id, { settings: { background_color: color, background_texture: texture } }))}
      >
        Save background
      </button>
    </fieldset>
  );
}
