// A line has one playback clock. The finished film carries its mix. While editing, a kept
// take or cached narration supplies the clock and the draft picture follows it.
import { Captions as CC, Pause, Play, Settings, Volume2, VolumeX } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { EpisodeFrame, EpisodeUnit, EpisodeView } from "../../api";
import { allLines, clockLine, frameSpot, mmss } from "../../episode";
import { Popover } from "../Popover";
import { Captions } from "./Captions";
import { Stage } from "./Stage";

type Props = {
  view: EpisodeView;
  frame: EpisodeFrame;
  unit?: EpisodeUnit;
  editingWindow?: boolean;
  speed: number;
  onSpeed: (speed: number) => void;
  captions: boolean;
  onCaptions: (show: boolean) => void;
  onProgress: (fraction: number | null) => void;
};

export function LinePlayer({ view, frame, unit, editingWindow, speed, onSpeed, captions, onCaptions, onProgress }: Props) {
  const line = clockLine(view, frame.id);
  const film = !editingWindow && view.film_state.status === "done" && !view.film_state.stale ? view.film_state.file?.url : undefined;
  const take = line?.source.kind === "take" ? view.takes.find((t) => t.id === line.source.take) : undefined;
  const sound = take?.audio?.url ?? take?.video?.url ?? line?.audio_url;
  const src = film ?? sound;
  const start = film ? (line?.start ?? frame.start) : take ? (line?.source.offset ?? 0) : 0;
  const seconds = Math.max(0.1, line?.seconds ?? frame.seconds);
  const incoming = useMemo(() => {
    const frames = allLines(view);
    const index = frames.findIndex(({line}) => line.id === frame.id);
    const previous = frames[index - 1]?.line;
    if (!previous || previous.presence === "content") return undefined;
    return frameSpot(view, previous);
  }, [view, frame.id]);
  const media = useRef<HTMLVideoElement>(null);
  const [position, setPosition] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [problem, setProblem] = useState("");
  const [volume, setVolume] = useState(1);
  const [muted, setMuted] = useState(false);
  const [settings, setSettings] = useState(false);
  const gear = useRef<HTMLButtonElement>(null);
  const pos = useRef(0);
  const seek = (time: number) => {
    pos.current = time;
    setPosition(time);
    if (media.current?.readyState) media.current.currentTime = start + time;
    onProgress(time / seconds);
  };
  useEffect(() => {
    if (media.current) {
      media.current.playbackRate = speed;
      media.current.volume = volume;
      media.current.muted = muted;
    }
  }, [volume, muted, speed, src]);
  useEffect(() => {
    if (!playing) return;
    let id = 0;
    let last = performance.now();
    let lastPaint = 0;
    const tick = (now: number) => {
      const next = media.current ? media.current.currentTime - start : pos.current + speed * (now - last) / 1000;
      pos.current = Math.min(seconds, Math.max(0, next));
      if ((incoming && !film && next < 0.45) || next >= seconds || now - lastPaint >= 65) {
        setPosition(pos.current);
        onProgress(pos.current / seconds);
        lastPaint = now;
      }
      last = now;
      if (next >= seconds) {
        media.current?.pause();
        setPlaying(false);
      } else id = requestAnimationFrame(tick);
    };
    id = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(id);
  }, [playing, start, seconds, onProgress, incoming, film, speed]);
  useEffect(() => {
    return () => onProgress(null);
  }, [onProgress]);
  const toggle = async () => {
    if (playing) {
      media.current?.pause();
      setPlaying(false);
      return;
    }
    if (position >= seconds - 0.05) seek(0);
    try {
      if (media.current) await media.current.play();
      setProblem("");
      setPlaying(true);
    } catch {
      setProblem("Playback could not start. Try again.");
    }
  };
  return (
    <div className="ep-line-player" role="group" aria-label="Line player">
      {!film && <Stage view={view} frame={frame} unit={unit} take={take} previewAt={position} incoming={incoming} motionTime={!editingWindow && (playing || position > 0) ? position / Math.min(0.45, seconds) : undefined} />}
      {src && (
        <video
          ref={media}
          src={src}
          playsInline
          preload="auto"
          hidden={!film}
          aria-label={film ? "Rendered line" : "Line audio"}
          onLoadedMetadata={() => {
            if (media.current) media.current.currentTime = start + pos.current;
          }}
          onEnded={() => {
            setPlaying(false);
            setPosition(seconds);
            pos.current = seconds;
            onProgress(1);
          }}
          onError={() => {
            setPlaying(false);
            setProblem("This media could not be played.");
          }}
        />
      )}
      {captions && <Captions words={frame.vo} progress={position / seconds} />}
      <div className="ep-player-controls">
        <button type="button" aria-label={playing ? "Pause line" : "Play line"} onClick={() => void toggle()}>
          {playing ? <Pause /> : <Play />}
        </button>
        <small>
          {mmss(position)} / {mmss(seconds)}
        </small>
        <input
          type="range"
          aria-label="Seek within line"
          min={0}
          max={seconds}
          step={0.05}
          value={position}
          onChange={(e) => seek(Number(e.target.value))}
        />
        <button
          type="button"
          aria-label={muted ? "Unmute" : "Mute"}
          disabled={!src}
          aria-pressed={muted}
          onClick={() => setMuted(!muted)}
        >
          {muted || !volume ? <VolumeX /> : <Volume2 />}
        </button>
        <input
          type="range"
          aria-label="Volume"
          min={0}
          max={1}
          step={0.05}
          value={muted ? 0 : volume}
          disabled={!src}
          onChange={(e) => {
            setMuted(false);
            setVolume(Number(e.target.value));
          }}
        />
        <button ref={gear} type="button" aria-label="Playback settings" aria-expanded={settings} aria-haspopup="dialog" onClick={() => setSettings(!settings)}><Settings /></button>
        <Popover open={settings} anchor={gear} onClose={() => setSettings(false)} title="Playback speed" side="top" align="end" width={156}>
          <div className="ep-rate-menu">{[0.5, 0.75, 1, 1.25, 1.5, 2].map(rate => (
            <button key={rate} type="button" aria-pressed={rate === speed} onClick={() => {onSpeed(rate); setSettings(false);}}>{rate}×</button>
          ))}</div>
        </Popover>
        <button type="button" aria-label="Show transcript" aria-pressed={captions} onClick={() => onCaptions(!captions)}>
          <CC />
        </button>
      </div>
      {(!src || problem) && (
        <small className="ep-player-message" role="status">
          {problem || "Silent draft"}
        </small>
      )}
    </div>
  );
}
