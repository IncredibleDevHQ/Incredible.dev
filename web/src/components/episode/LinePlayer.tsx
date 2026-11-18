// A line has one playback clock. The finished film carries its mix. While editing, a kept
// take or cached narration supplies the clock and the draft picture follows it.
import { Captions as CC, Pause, Play, Settings, Volume2, VolumeX } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { EpisodeFrame, EpisodeUnit, EpisodeView } from "../../api";
import { allLines, clockLine, frameSpot, mmss } from "../../episode";
import { Popover } from "../Popover";
import { Captions } from "./Captions";
import { Stage } from "./Stage";

type Props = {
  view: EpisodeView;
  frame: EpisodeFrame;
  unit?: EpisodeUnit;
  // the picture is one of its earlier versions: it plays as a draft, never from the rendered film
  draft?: boolean;
  editingWindow?: boolean;
  cameraPoster: ReactNode;
  autoStart?: boolean;
  initialPosition?: number;
  chapter?: { start: number; nextStart?: number; total: number; seek: (time: number, play: boolean) => void };
  onFinish?: () => void;
  audioControls?: { volume: number; muted: boolean; setVolume: (v: number) => void; setMuted: (v: boolean) => void };
  speed: number;
  onSpeed: (speed: number) => void;
  captions: boolean;
  onCaptions: (show: boolean) => void;
  onProgress: (fraction: number | null) => void;
};

export function LinePlayer({ view, frame, unit, draft, editingWindow, cameraPoster, autoStart, initialPosition = 0, chapter, onFinish, audioControls, speed, onSpeed, captions, onCaptions, onProgress }: Props) {
  const line = clockLine(view, frame.id);
  const film = !editingWindow && !draft && view.film_state.status === "done" && !view.film_state.stale ? view.film_state.file?.url : undefined;
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
  const [position, setPosition] = useState(initialPosition);
  const [playing, setPlaying] = useState(false);
  const [problem, setProblem] = useState("");
  const [lineVolume, setLineVolume] = useState(1);
  const [lineMuted, setLineMuted] = useState(false);
  const { volume, setVolume, muted, setMuted } = audioControls ?? { volume: lineVolume, setVolume: setLineVolume, muted: lineMuted, setMuted: setLineMuted };
  const finish = useRef(onFinish);
  finish.current = onFinish;
  const ended = useRef(false);
  const complete = () => {
    if (ended.current) return;
    ended.current = true;
    media.current?.pause();
    setPlaying(false);
    finish.current?.();
  };
  const [settings, setSettings] = useState(false);
  const gear = useRef<HTMLButtonElement>(null);
  const pos = useRef(initialPosition);
  const elapsed = (chapter?.start ?? 0) + position;
  const duration = chapter?.total ?? seconds;
  const chapterEnded = !!chapter && chapter.nextStart === undefined && position >= seconds - 0.001;
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
        complete();
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
    if (chapter && chapterEnded) {
      chapter.seek(0, true);
      return;
    }
    if (!chapter && position >= seconds - 0.05) seek(0);
    ended.current = false;
    try {
      if (media.current) await media.current.play();
      setProblem("");
      setPlaying(true);
    } catch {
      setProblem("Playback could not start. Try again.");
    }
  };
  useEffect(() => {
    if (!autoStart) return;
    const video = media.current;
    if (!video) { setPlaying(true); return; }
    let active = true;
    void video.play().then(() => { if (active) setPlaying(true); }).catch(() => {
      if (active) setProblem("Press play to continue this chapter.");
    });
    return () => { active = false; };
  }, [autoStart]);
  const renderedVisual = film && (take?.video || frame.presence === "content");
  const showPoster = !editingWindow && !playing && position === 0;
  const showStill = showPoster && unit?.picture.stills[frame.id] && !take?.video;
  return (
    <div className="ep-line-player" role="group" aria-label={chapter ? "Chapter player" : "Line player"}>
      {!renderedVisual && <Stage view={view} frame={frame} unit={unit} take={take} previewAt={showStill ? undefined : position} incoming={incoming} motionTime={!editingWindow && (playing || position > 0) ? position / Math.min(0.45, seconds) : undefined} />}
      {src && (
        <video
          ref={media}
          src={src}
          playsInline
          preload="auto"
          hidden={!renderedVisual}
          aria-label={film ? "Rendered line" : "Line audio"}
          onLoadedMetadata={() => {
            if (media.current) media.current.currentTime = start + pos.current;
          }}
          onEnded={() => {
            complete();
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
      {cameraPoster && !editingWindow && <div className="ep-player-poster">{cameraPoster}</div>}
      {captions && <Captions words={frame.vo} progress={position / seconds} />}
      <div className="ep-player-controls">
        <button type="button" aria-label={chapter ? (playing ? "Pause chapter" : chapterEnded ? "Replay chapter" : "Resume chapter") : (playing ? "Pause line" : "Play line")} onClick={() => void toggle()}>
          {playing ? <Pause /> : <Play />}
        </button>
        <small>
          {mmss(elapsed)} / {mmss(duration)}
        </small>
        <input
          type="range"
          className="ep-playback-seek"
          aria-label={chapter ? "Seek within chapter" : "Seek within line"}
          min={0}
          max={duration}
          step={chapter ? "any" : 0.05}
          value={elapsed}
          onChange={e => {
            const time = e.currentTarget.valueAsNumber;
            if (chapter && (time < chapter.start || (chapter.nextStart !== undefined && time >= chapter.nextStart))) {
              chapter.seek(time, playing);
            } else {
              seek(Math.min(seconds, Math.max(0, time - (chapter?.start ?? 0))));
            }
          }}
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
