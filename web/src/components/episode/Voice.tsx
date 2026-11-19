// Account voices and local recording setup for the episode narrator.
import { Mic, Play, Plus, Square, Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api, type ChannelVoice, type EpisodeView, type Voice, type VoiceCloneInput } from "../../api";
import { mmss } from "../../episode";
import { MAX_SAMPLE_BYTES, useVoiceSample } from "./voiceSample";
import { Select } from "../Select";
import { TextField } from "../TextField";
import type { Run } from "./Ask";

export function NarratorVoice({ view, run, busy }: { view: EpisodeView; run: Run; busy: boolean }) {
  const [voices, setVoices] = useState<Voice[] | null>(null);
  const [problem, setProblem] = useState("");
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
  const preview = listed.find((v) => v.id === current)?.preview;
  return (
    <span className="ep-voice">
      <Select
        size="sm"
        aria-label="The narrator's voice"
        placeholder={voices || problem ? "Pick a voice" : "Reading the voices"}
        value={current}
        options={options}
        disabled={busy || options.length === 0}
        onChange={(id, option) =>
          id !== current && void run(() => api.chooseEpisode(view.id, { settings: { narrator: { id, name: option.label } } }))
        }
      />
      {preview && <audio controls preload="none" aria-label="ElevenLabs voice sample" src={preview} />}
      {problem && (
        <small data-tone="red" role="alert">
          {problem}
        </small>
      )}
      {picked?.verify && <small data-tone="amber">ElevenLabs asks you to verify this voice on its site before it speaks.</small>}
    </span>
  );
}

export function ChannelVoices({ episode, voices, selected, busy, onSelect, onAdd, addLabel }: {
  episode?: string; voices: ChannelVoice[]; selected?: ChannelVoice; busy: boolean; addLabel?: string;
  onSelect: (id: string) => void; onAdd: () => void;
}) {
  return (
    <div className="ep-channel-voices">
      <div className="ep-channel-voice-picker">
        {voices.length > 0 ? (
          <Select label="Channel voices" size="sm" value={selected?.id ?? null}
            placeholder="Choose a cloned voice" disabled={busy}
            options={voices.map(voice => ({ value: voice.id, label: voice.name }))}
            onChange={onSelect} />
        ) : <span>Channel voices</span>}
        <button className="btn ep-add-voice" type="button" disabled={busy}
          aria-label="Add cloned voice" title="Add cloned voice" onClick={onAdd}>
          <Plus aria-hidden="true" />{addLabel ?? (voices.length === 0 && "Add voice")}
        </button>
      </div>
      {selected && episode && <VoicePreview key={selected.id} episode={episode} voice={selected} />}
    </div>
  );
}

function VoicePreview({ episode, voice }: { episode: string; voice: ChannelVoice }) {
  const [sample, setSample] = useState(voice.preview ?? "");
  const [loading, setLoading] = useState(false);
  const [problem, setProblem] = useState("");
  const [autoPlay, setAutoPlay] = useState(false);

  const play = async () => {
    setLoading(true);
    setProblem("");
    try {
      const result = await api.previewChannelVoice(episode, voice.id);
      setAutoPlay(true);
      setSample(result.url);
    } catch (error) {
      setProblem((error as Error).message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="ep-voice">
      {sample ? (
        <audio controls autoPlay={autoPlay} src={sample} aria-label={`Sample of ${voice.name}`}
          onError={() => { setSample(""); setProblem("The sample didn’t load. Try playing it again."); }} />
      ) : (
        <button className="btn" type="button" disabled={loading} onClick={() => void play()}>
          <Play aria-hidden="true" /> {loading ? "Preparing sample" : "Play sample"}
        </button>
      )}
      {voice.verify && !sample && <small data-tone="amber">ElevenLabs may ask the speaker to verify this voice before it can speak.</small>}
      {problem && <small data-tone="red" role="alert">{problem}</small>}
    </div>
  );
}

export function CloneDialog({ onClone, onDone }: {
  onClone: (clone: VoiceCloneInput & { file: File }) => Promise<boolean>;
  onDone: () => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState("");
  useEffect(() => {
    if (!file || !file.size || file.size > MAX_SAMPLE_BYTES) { setPreview(""); return; }
    const url = URL.createObjectURL(file);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);
  const [name, setName] = useState("My voice");
  const [mine, setMine] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const sample = useVoiceSample((next) => { setFile(next); setProblem(""); setMine(false); });
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const node = dialog.current;
    node?.showModal();
    return () => node?.close();
  }, []);
  const input = useRef<HTMLInputElement>(null);
  const fileProblem = file && (!file.size ? "This recording is empty." : file.size > MAX_SAMPLE_BYTES ? "Choose a recording under 25 MiB." : "");
  const ready = file && !fileProblem && name.trim() && mine && sample.phase === "idle" && !busy;
  const backdropPress = useRef(false);
  function outside(event: React.MouseEvent<HTMLDialogElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    return event.target === event.currentTarget && (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom);
  }
  const make = async () => {
    if (!file || !ready) return;
    setBusy(true);
    setProblem("");
    try {
      if (await onClone({ name: name.trim(), consent: mine, file })) onDone();
    } catch (error) {
      setProblem(error instanceof Error ? error.message : "Voice cloning failed. Try again.");
    } finally {
      setBusy(false);
    }
  };
  return (
    <dialog
      ref={dialog}
      aria-labelledby="ep-clone-title"
      className="ep-clone-dialog"
      onPointerDown={e => { backdropPress.current = outside(e); }}
      onClick={e => { if (!busy && backdropPress.current && outside(e)) onDone(); }}
      onCancel={(e) => {
        e.preventDefault();
        if (!busy) onDone();
      }}
    >
      <h2 id="ep-clone-title">Clone your voice</h2>
      <p>Record or upload a sample. The cloned voice is saved to this channel and selected for this episode.</p>
      <form
        className="ep-clone"
        onSubmit={(e) => {
          e.preventDefault();
          if (ready) void make();
        }}
      >
        <TextField size="sm" label="Name" value={name} maxLength={60} disabled={busy} onChange={(e) => setName(e.target.value)} />
        <section className="ep-sample-script" aria-label="Reading script">
          <h3>Read aloud <small>About 1 minute</small></h3>
          <p>Last Saturday, I took a map and a bottle of water and set out for the river. At the corner, a small sign pointed down a street I’d never noticed. Where did it go? I had time to find out. I turned left, passed a bakery, and followed the sound of running water.</p>
          <p>Just beyond the bridge, a woman was painting the view. I asked what she liked most about it. She set down her brush and pointed to the sky. “Wait a moment,” she said. A cloud moved, the water caught the light, and suddenly I saw what she meant. I stayed for a while. On the way home, I folded up the map and put it in my pocket.</p>
        </section>
        <div className="ep-sample-actions">
          {sample.phase === "recording" ? (
            <button type="button" className="btn" onClick={sample.stop}><Square />Stop recording</button>
          ) : (
            <button type="button" className="btn" disabled={busy || sample.phase !== "idle"} onClick={() => void sample.start()}>
              <Mic />{sample.phase === "asking" ? "Waiting for microphone" : sample.phase === "stopping" ? "Finishing recording" : "Record sample"}
            </button>
          )}
          <button type="button" className="btn" disabled={busy || sample.phase !== "idle"} onClick={() => input.current?.click()}><Upload />Upload file</button>
          {sample.phase === "recording" && <span>Recording · {mmss(sample.elapsed)}</span>}
          <input ref={input} type="file" accept="audio/*,video/mp4,video/quicktime,video/webm" hidden
            onChange={e => {
              const next = e.target.files?.[0];
              if (next) { setFile(next); setProblem(""); sample.clearError(); setMine(false); }
              e.target.value = "";
            }} />
        </div>
        {file && sample.phase === "idle" && <div className="ep-sample-preview"><small>{file.name}</small>
          {preview && <audio controls src={preview} aria-label="Preview recording" />}
        </div>}
        <label className="ep-check">
          <input type="checkbox" disabled={busy} checked={mine} onChange={(e) => setMine(e.target.checked)} />
          <span>This is my voice, or its speaker agreed. The recording goes to ElevenLabs.</span>
        </label>
        {(fileProblem || sample.error || problem) && (
          <small role="alert" data-tone="red">
            {fileProblem || sample.error || problem}
          </small>
        )}
        <div className="ep-clone-actions">
          <button type="button" className="btn" disabled={busy} onClick={onDone}>
            Cancel
          </button>
          <button type="submit" className="btn primary" disabled={!ready}>
            {busy ? "Cloning" : "Clone and use voice"}
          </button>
        </div>
      </form>
    </dialog>
  );
}
