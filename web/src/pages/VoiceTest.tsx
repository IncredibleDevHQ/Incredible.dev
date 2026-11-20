import { useEffect, useRef, useState } from "react";
import { BookOpen, Mic, Upload } from "lucide-react";
import { api, type VoiceTestClip } from "../api";
import { TextField } from "../components/TextField";
import { MAX_SAMPLE_BYTES, useVoiceSample } from "../components/episode/voiceSample";
import { prepareVoiceTest } from "./voiceTestAudio";
import { scripts } from "./voiceTestScripts";

function Player({ audio, label }: {audio: Blob; label: string}) {
  const [url, setUrl] = useState("");
  useEffect(() => {
    const url = URL.createObjectURL(audio);
    setUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [audio]);
  return <audio controls preload="metadata" aria-label={label} src={url || undefined} />;
}

function Comparison({episode, clip, locked, reuse}: {episode: string; clip: VoiceTestClip; locked: boolean; reuse: (audio: Blob) => void}) {
  const [pair, setPair] = useState<Blob[]>([]);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    setError("");
    Promise.all([api.voiceTestAudio(episode, clip.id, "original"), api.voiceTestAudio(episode, clip.id, "clone")])
      .then(audio => { if (active) setPair(audio); })
      .catch((e: Error) => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [episode, clip.id, attempt]);
  if (error) return <p role="alert">{error} <button className="btn" onClick={() => setAttempt(n=>n+1)}>Retry playback</button></p>;
  if (!pair.length) return <p role="status">Loading audio…</p>;
  return <div className="lab-players">
    <div><strong>Original</strong><Player label="Source playback" audio={pair[0]} /></div>
    <button className="btn" disabled={locked} onClick={()=>reuse(pair[0])}>Use this recording</button>
    <div><strong>Clone</strong><Player label="Cloned playback" audio={pair[1]} />{clip.text && <p>{clip.text}</p>}</div>
  </div>;
}

export function VoiceTest({episode}: {episode: string}) {
  const picker = useRef<HTMLInputElement>(null);
  const [sample, setSample] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [newWords, setNewWords] = useState(true);
  const [text, setText] = useState("Tomorrow we’ll catch the early train. Have you ever seen the city just before sunrise?");
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [listError, setListError] = useState("");
  const [clips, setClips] = useState<VoiceTestClip[]>([]);
  const [selected, setSelected] = useState("");
  const [script, setScript] = useState<keyof typeof scripts>("The repair shop");
  const details = useRef<HTMLDetailsElement>(null);
  const sampleVersion = useRef(0);
  const [preparing, setPreparing] = useState(false);
  const accept = async (file: File, label: string) => {
    const version = ++sampleVersion.current;
    setError(""); setConsent(false); setPreparing(true); setSample(null);
    try {
      if (!file.size || file.size > MAX_SAMPLE_BYTES) throw new Error("Choose a non-empty audio file under 25 MiB.");
      const decoded = await prepareVoiceTest(file);
      if (version === sampleVersion.current) { setSample(decoded); setName(label.slice(0,80)); }
    } catch (e) {
      if (version === sampleVersion.current) setError(e instanceof DOMException ? "This audio could not be opened. Try a WAV or MP3 file." : (e as Error).message);
    } finally {
      if (version === sampleVersion.current) setPreparing(false);
    }
  };
  const recorder = useVoiceSample(file => void accept(file, "My recording"));
  const locked = busy || preparing || recorder.phase !== "idle";

  useEffect(() => {
    let active = true;
    api.voiceTests(episode).then(({clips}) => {
      if (active) {
        setClips(current => [...current, ...clips.filter(c => !current.some(row=>row.id===c.id))]);
        setSelected(current => current || clips[0]?.id || "");
      }
    }).catch((e: Error) => { if (active) setListError(e.message); });
    return () => { active = false; };
  }, [episode]);

  useEffect(() => {
    if (!clips.length) return;
    const expiry = Math.min(...clips.map(c => c.expires_at * 1000));
    const timer = window.setTimeout(() => setClips(current =>
      current.filter(c => c.expires_at * 1000 > Date.now())), Math.max(0, expiry - Date.now()));
    return () => window.clearTimeout(timer);
  }, [clips]);

  async function create() {
    if (locked || !sample || !name.trim() || !consent || (newWords && !text.trim())) return;
    setBusy(true); setError("");
    try {
      const clip = await api.createVoiceTest(episode, {name: name.trim(), file: sample, consent, text: newWords ? text.trim() : undefined});
      setClips(current => [clip,...current]); setSelected(clip.id);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  const clip = clips.find(c=>c.id===selected) ?? clips[0];
  return <main className="voice-lab" onPlayCapture={event => {
    if (event.target instanceof HTMLAudioElement)
      event.currentTarget.querySelectorAll("audio").forEach(el => { if (el !== event.target) el.pause(); });
  }}>
    <header><h1>Voice test</h1><p>Hear your cloned voice read a passage of your choice.</p></header>
    <div className="lab-layout">
      <section className="lab-card">
        <h2>Source audio</h2>
        <p className="muted">Upload or record up to five minutes of your voice.</p>
        <div className="lab-buttons">
          <button className="btn" disabled={locked} onClick={()=>picker.current?.click()}><Upload />Upload audio</button>
          {recorder.phase === "recording" ?
            <button className="btn primary" onClick={recorder.stop}>Stop recording · {recorder.elapsed}s</button> :
            <button className="btn" disabled={locked} onClick={()=>{ setError(""); if (details.current) details.current.open=true; void recorder.start(); }}><Mic />Record audio</button>}
        </div>
        <input hidden type="file" ref={picker} accept="audio/*,.m4a,.webm" onChange={e=>{
          const file=e.target.files?.[0]; e.target.value="";
          if (file) { recorder.clearError(); void accept(file,file.name.replace(/\.[^.]+$/, "") || "My recording"); }
        }} />
        <details ref={details}><summary><BookOpen />Reading scripts</summary>
          <div className="lab-buttons">{(Object.keys(scripts) as (keyof typeof scripts)[]).map(key=>
            <button key={key} className="btn" aria-pressed={key===script} onClick={()=>setScript(key)}>{key}</button>)}</div>
          <article>{scripts[script].map(p=><p key={p}>{p}</p>)}</article>
        </details>
        {preparing && <p role="status">Preparing audio…</p>}
        {sample && <>
          <Player audio={sample} label="Original audio playback" />
          <TextField label="Recording label" value={name} disabled={locked} maxLength={80} onChange={e=>setName(e.target.value)} />
          <button className="btn" disabled={!name.trim()} onClick={()=>{
            const url=URL.createObjectURL(sample);
            const link=document.createElement("a"); link.href=url; link.download=name.trim().replace(/[/\\:*?"<>|]/g,"-")+".wav";
            link.click(); window.setTimeout(()=>URL.revokeObjectURL(url),1000);
          }}>Save recording</button>
          <div className="lab-buttons" role="group" aria-label="Clone playback mode">
            <button className="btn" disabled={locked} aria-pressed={newWords} onClick={()=>setNewWords(true)}>Read new words</button>
            <button className="btn" disabled={locked} aria-pressed={!newWords} onClick={()=>setNewWords(false)}>Repeat recording</button>
          </div>
          {newWords && <TextField label="What should the clone say?" value={text} maxLength={2000} disabled={locked}
            onChange={event=>setText(event.target.value)} />}
          <label className="ep-check"><input type="checkbox" disabled={locked} checked={consent} onChange={e=>setConsent(e.target.checked)} />This is my voice. Send it to ElevenLabs.</label>
        </>}
        <button className="btn primary" disabled={locked || !sample || !name.trim() || !consent || (newWords && !text.trim())} onClick={()=>void create()}>
          {busy ? "Creating test clone…" : "Create test clone"}
        </button>
        {(error || recorder.error) && <p role="alert">{error || recorder.error}</p>}
      </section>
      <section className="lab-card"><h2>Listen to clones</h2>
        <p className="muted">Saved on this test page for one hour.</p>
        {listError && <p role="alert">{listError}</p>}
        {!clips.length && <p className="lab-empty">Your test clones will appear here.</p>}
        {clips.length > 0 && <div className="lab-versions">{clips.map((c,i)=>
          <button className="btn" key={c.id} aria-pressed={clip?.id===c.id} onClick={()=>setSelected(c.id)}>
            {c.name} · {clips.length-i}
          </button>)}</div>}
        {clip && <Comparison key={clip.id} episode={episode} clip={clip} locked={locked} reuse={audio=>{
          setNewWords(true);
          void accept(new File([audio], "recording.wav", {type: "audio/wav"}), clip.name);
        }} />}
      </section>
    </div>
  </main>;
}
