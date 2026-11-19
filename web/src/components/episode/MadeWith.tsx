// What a made picture was made with: its agent's mark, then the model and the effort its record
// names. One quiet chip, so it reads the same on a picture's card and over the frame.
import type { EpisodeUnit, EpisodeView } from "../../api";
import { AgentMark } from "../../ui";
import { Tooltip } from "../Tooltip";
import { madeOn, pickLabel } from "./models";
import { pictureProvider } from "./pictureProvider";

// Whether a made picture was made with something other than what its beat is set to now: another
// agent, model or effort. A card that already names the beat's choice says the other only then.
export function madeOtherwise(view: EpisodeView, unit: EpisodeUnit): boolean {
  const p = unit.picture;
  if ((p.status !== "made" && p.status !== "go") || !p.generation) return false;
  if (pictureProvider(unit, view.options.picture_writers) !== unit.builder) return true;
  return madeOn(p.generation) !== pickLabel(view.options.generation_models[unit.builder], unit.model_now ?? unit.model_pick);
}

export function MadeWith({ view, unit }: { view: EpisodeView; unit: EpisodeUnit }) {
  const p = unit.picture;
  if ((p.status !== "made" && p.status !== "go") || !p.generation) return null;
  const builder = pictureProvider(unit, view.options.picture_writers);
  const agent = view.options.picture_writers.find((w) => w.id === builder)?.title ?? view.options.writers.find((w) => w.id === builder)?.title ?? builder;
  const on = madeOn(p.generation);
  const said = `Made with ${[agent, on].filter(Boolean).join(" · ")}`;
  return (
    <Tooltip content={on ? said : `${said}, on its own default model`} side="bottom">
      <span className="ep-made-with" role="img" aria-label={said}>
        <AgentMark mark={builder} size="sm" />
        <span aria-hidden="true">{on || agent}</span>
      </span>
    </Tooltip>
  );
}
