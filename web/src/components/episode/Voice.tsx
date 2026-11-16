// The narrator's voice, under the film's Voice choice: which of the ElevenLabs account's voices
// says the lines nobody recorded, and a clone of the person's own voice, made from the takes
// they kept or from a recording they bring. A recording leaves this computer for ElevenLabs, so
// the form says so and waits for the person to say the voice is theirs to clone.
import { Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api, type EpisodeView, type Voice } from "../../api";
import { mmss } from "../../episode";
import { Popover } from "../Popover";
import { SegmentedControl } from "../SegmentedControl";
import { Select } from "../Select";
import { TextField } from "../TextField";
import type { Run } from "./Ask";

// The least speech a clone is made from, in seconds: the desk's own limit.
const LEAST = 30;

export function NarratorVoice({ view, run, busy }: { view: EpisodeView; run: Run; busy: boolean }) {
  const [voices, setVoices] = useState<Voice[] | null>(null);
  const [problem, setProblem] = useState("");
  const [cloning, setCloning] = useState(false);
  const button = useRef<HTMLButtonElement>(null);
  const picked = view.settings.narrator;
  // The account's voices, read when the narrator is chosen and again when a clone lands.
  useEffect(() => {
    let live = true;
    api.voices().then(
      (found) => {
        if (!live) return;
        setVoices(found.voices);
        setProblem("");
      },
      (error: Error) => live && setProblem(error.message),
    );
    return () => {
      live = false;
    };
  }, [picked?.id]);
  const listed = voices ?? [];
  const options = [
    // a voice picked before, which the account no longer lists, is still named
    ...(picked && !listed.some((v) => v.id === picked.id) ? [{ value: picked.id, label: picked.name }] : []),
    ...listed.map((v) => ({ value: v.id, label: v.name, description: v.usual ? "The house's voice" : v.own ? "Yours" : undefined })),
  ];
  const current = picked?.id ?? listed.find((v) => v.usual)?.id ?? null;
  return (
    <span className="ep-voice">
      <Select
        size="sm"
        aria-label="The narrator's voice"
        placeholder={voices || problem ? "Pick a voice" : "Reading the voices"}
        value={current}
        options={options}
        disabled={busy || options.length === 0}
        onChange={(id, option) => id !== current && void run(() => api.chooseEpisode(view.id, { settings: { narrator: { id, name: option.label } } }))}
      />
      <button ref={button} type="button" className="btn" aria-haspopup="dialog" aria-expanded={cloning} disabled={busy} onClick={() => setCloning((open) => !open)}>
        Clone your voice
      </button>
      <Popover
        open={cloning}
        onClose={() => setCloning(false)}
        anchor={button}
        side="top"
        align="end"
        width={340}
        title="Clone your voice"
        description="ElevenLabs makes a voice from a recording of you. It says the lines you haven't recorded."
      >
        <CloneForm view={view} run={run} onDone={() => setCloning(false)} />
      </Popover>
      {problem && (
        <small data-tone="red" role="alert">
          {problem}
        </small>
      )}
      {picked?.verify && <small data-tone="amber">ElevenLabs asks you to verify this voice on its site before it speaks.</small>}
    </span>
  );
}

function CloneForm({ view, run, onDone }: { view: EpisodeView; run: Run; onDone: () => void }) {
  const seconds = view.takes.filter((t) => t.kept && t.audio).reduce((sum, t) => sum + t.seconds, 0);
  const enough = seconds >= LEAST;
  const [from, setFrom] = useState<"takes" | "file">(enough ? "takes" : "file");
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("My voice");
  const [mine, setMine] = useState(false);
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const ready = name.trim() !== "" && mine && (from === "takes" ? enough : file !== null) && !busy;
  const make = async () => {
    setBusy(true);
    const made = await run(() => api.cloneVoice(view.id, { name: name.trim(), consent: mine, file: from === "file" ? (file ?? undefined) : undefined }));
    setBusy(false);
    if (made) onDone();
  };
  return (
    <form
      className="ep-clone"
      onSubmit={(e) => {
        e.preventDefault();
        if (ready) void make();
      }}
    >
      <TextField size="sm" label="Name" value={name} maxLength={60} onChange={(e) => setName(e.target.value)} />
      <SegmentedControl
        size="sm"
        aria-label="What the voice is made from"
        value={from}
        onChange={setFrom}
        options={[
          { value: "takes", label: `Your takes · ${mmss(seconds)}`, disabled: !enough },
          { value: "file", label: "A recording" },
        ]}
      />
      {from === "file" && (
        <>
          <button type="button" className="btn" onClick={() => input.current?.click()}>
            <Upload />
            <span>{file ? file.name : "Choose a recording"}</span>
          </button>
          <input ref={input} type="file" accept="audio/*,video/mp4,video/quicktime,video/webm" hidden onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </>
      )}
      <small>{enough || from === "file" ? "A minute or two of clear speech works best." : `Your takes need ${LEAST} seconds or more to clone from.`}</small>
      <label className="ep-check">
        <input type="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} />
        <span>This is my voice, or its speaker agreed. The recording goes to ElevenLabs.</span>
      </label>
      <div className="ep-clone-actions">
        <button type="button" className="btn" onClick={onDone}>
          Cancel
        </button>
        <button type="submit" className="btn primary" disabled={!ready}>
          {busy ? "Cloning" : "Clone it"}
        </button>
      </div>
    </form>
  );
}
