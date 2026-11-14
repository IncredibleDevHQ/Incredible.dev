// The frame as the film will have it for one line: the person's window and the picture's box,
// placed by the same table the film is rendered from. The person is the live camera while
// recording, the take once there is one, and a stand-in before that. The picture is its posed
// still, its draft clip while playing, or a sketch of what the plan says it shows.
import { useEffect, useRef } from "react";
import type { EpisodeFrame, EpisodeTake, EpisodeUnit, EpisodeView } from "../../api";
import { boxStyle, clockLine, spotOf } from "../../episode";

export type Playing = { from: number; to: number; of: "take" | "clip" } | null;

export function Stage({
  view,
  frame,
  unit,
  take,
  stream,
  playing,
  onEnded,
  small,
}: {
  view: EpisodeView;
  frame: EpisodeFrame;
  unit?: EpisodeUnit;
  take?: EpisodeTake;
  stream?: MediaStream | null;
  playing?: Playing;
  onEnded?: () => void;
  small?: boolean;
}) {
  const spot = spotOf(view, frame.layout);
  const size = view.options.geometry.frame;
  const person = frame.presence !== "content" ? spot.person : null;
  const picture = frame.presence !== "person" ? spot.picture : null;
  const still = unit?.picture.stills[frame.id];
  const clip = unit?.picture.clip;
  const line = clockLine(view, frame.id);
  const offset = line?.source.kind === "take" ? (line.source.offset ?? 0) : 0;
  const showsClip = playing?.of === "clip" && clip;
  return (
    <div className="ep-stage" data-small={small || undefined} aria-label="The frame for this line">
      {picture && (
        <div className="ep-stage-pic" data-glass={spot.glass || undefined} style={boxStyle(picture, size, spot.picture_radius)}>
          {showsClip ? (
            <Reel src={clip.url} from={playing.from} to={playing.to} onEnded={onEnded} />
          ) : still ? (
            <img src={still.url} alt={frame.shows ?? "The picture for this line"} />
          ) : (
            <Sketch frame={frame} unit={unit} />
          )}
        </div>
      )}
      {person && (
        <div className="ep-stage-person" style={boxStyle(person, size, spot.person_radius)}>
          {stream ? (
            <Live stream={stream} />
          ) : take?.video ? (
            <Reel
              key={take.id}
              src={take.video.url}
              from={playing?.of === "take" ? playing.from : offset}
              to={playing?.of === "take" ? playing.to : undefined}
              paused={playing?.of !== "take"}
              sound
              zoom={spot.zoom}
              onEnded={onEnded}
            />
          ) : (
            <span className="ep-stand-in" aria-label="Where you will be">
              <i />
              <b />
            </span>
          )}
        </div>
      )}
      {/* A take with no picture of you (a voice-only film) still has to be heard when played. */}
      {!person && playing?.of === "take" && take && (take.audio ?? take.video) && (
        <Reel src={(take.audio ?? take.video)!.url} from={playing.from} to={playing.to} sound hidden onEnded={onEnded} />
      )}
    </div>
  );
}

// The camera as it is being recorded, mirrored the way a person expects to see themself.
function Live({ stream }: { stream: MediaStream }) {
  const video = useRef<HTMLVideoElement>(null);
  useEffect(() => {
    if (video.current) video.current.srcObject = stream;
  }, [stream]);
  return <video ref={video} className="ep-live" autoPlay muted playsInline />;
}

// A stretch of a file: held on its first frame, or played from `from` to `to`.
function Reel({
  src,
  from,
  to,
  paused,
  sound,
  zoom,
  hidden,
  onEnded,
}: {
  src: string;
  from: number;
  to?: number;
  paused?: boolean;
  sound?: boolean;
  zoom?: number;
  hidden?: boolean;
  onEnded?: () => void;
}) {
  const video = useRef<HTMLVideoElement>(null);
  useEffect(() => {
    const el = video.current;
    if (!el) return;
    const seek = () => {
      el.currentTime = Math.max(0, from);
      if (paused) el.pause();
      else void el.play().catch(() => undefined);
    };
    if (el.readyState >= 1) seek();
    else el.addEventListener("loadedmetadata", seek, { once: true });
    return () => el.removeEventListener("loadedmetadata", seek);
  }, [src, from, paused]);
  return (
    <video
      ref={video}
      src={src}
      muted={!sound || paused}
      playsInline
      preload="auto"
      hidden={hidden}
      style={zoom && zoom !== 1 ? { transform: `scale(${zoom})` } : undefined}
      onTimeUpdate={(e) => {
        if (paused || to === undefined || e.currentTarget.currentTime < to) return;
        e.currentTarget.pause();
        onEnded?.();
      }}
      onEnded={() => !paused && onEnded?.()}
    />
  );
}

// Before a picture is built: what the plan says it shows, and the things it will hold.
function Sketch({ frame, unit }: { frame: EpisodeFrame; unit?: EpisodeUnit }) {
  const words = (frame.objects ?? []).map((o) => o.words || o.what).filter(Boolean).slice(0, 6);
  return (
    <span className="ep-sketch">
      <span className="ep-sketch-text">{frame.shows || unit?.shows || "A picture for this line"}</span>
      {words.length > 0 && (
        <span className="ep-sketch-chips">
          {words.map((w, i) => (
            <i key={i}>{w}</i>
          ))}
        </span>
      )}
    </span>
  );
}

// A layout as a thumbnail: where the person and the picture sit.
export function LayoutThumb({ view, layout }: { view: EpisodeView; layout: string }) {
  const spot = spotOf(view, layout);
  const size = view.options.geometry.frame;
  return (
    <span className="ep-thumb" aria-hidden="true">
      {spot.picture && <i className="pic" data-glass={spot.glass || undefined} style={boxStyle(spot.picture, size, spot.picture_radius)} />}
      {spot.person && <i className="who" style={boxStyle(spot.person, size, spot.person_radius)} />}
    </span>
  );
}
