// The frame as the film will have it for one line: the person's window and the picture's box,
// placed by the same table the film is rendered from. The person is the live camera while
// recording, the take once there is one, and a stand-in before that. The picture is its posed
// still, its draft clip while playing, or a sketch of what the plan says it shows.
import { animationTime } from "./animationTime";
import { portraitUrl } from "./portraits";
import { useEffect, useRef } from "react";
import type { LayoutSpot, EpisodeFrame, EpisodeTake, EpisodeUnit, EpisodeView } from "../../api";
import { boxStyle, clockLine, frameSpot, spotOf } from "../../episode";

export function Stage({
  view,
  frame,
  unit,
  take,
  stream,
  previewAt,
  incoming,
  motionTime,
}: {
  view: EpisodeView;
  frame: EpisodeFrame;
  unit?: EpisodeUnit;
  take?: EpisodeTake;
  stream?: MediaStream | null;
  previewAt?: number;
  incoming?: LayoutSpot;
  motionTime?: number;
}) {
  const spot = frameSpot(view, frame);
  // Match the exported GSAP power2.inOut interpolation on the selected line's clock.
  const t = Math.max(0, Math.min(1, motionTime ?? 1));
  const ease = t < 0.5 ? 4 * t ** 3 : 1 - ((-2 * t + 2) ** 3) / 2;
  const mix = (a: number, b: number) => a + (b - a) * ease;
  let box = spot.person, radius = spot.person_radius, zoom = spot.zoom;
  if (t < 1 && incoming?.person && box) {
    const from = incoming.person;
    radius = mix(Math.min(incoming.person_radius, from[2] / 2, from[3] / 2), Math.min(radius, box[2] / 2, box[3] / 2));
    box = [mix(from[0], box[0]), mix(from[1], box[1]), mix(from[2], box[2]), mix(from[3], box[3])];
    zoom = mix(incoming.zoom, zoom);
  }
  const size = view.options.geometry.frame;
  const person = frame.presence !== "content" ? box : null;
  const picture = frame.presence !== "person" ? spot.picture : null;
  const still = unit?.picture.stills[frame.id];
  const clip = unit?.picture.clip;
  const line = clockLine(view, frame.id);
  const offset = line?.source.kind === "take" ? (line.source.offset ?? 0) : 0;
  return (
    <div className="ep-stage" aria-label="The frame for this line">
      {picture && (
        <div className="ep-stage-pic" data-glass={spot.glass || undefined} style={boxStyle(picture, size, spot.picture_radius)}>
          {previewAt !== undefined && clip ? (
            <ScrubVideo src={clip.url} time={animationTime(frame, unit, previewAt, line?.seconds || frame.seconds || 1)} />
          ) : still ? (
            <img src={still.url} alt={frame.shows ?? "The picture for this line"} />
          ) : (
            <Sketch frame={frame} unit={unit} />
          )}
        </div>
      )}
      {person && (
        <div className="ep-stage-person" data-editing={motionTime === undefined || undefined} style={boxStyle(person, size, radius)}>
          {stream ? (
            <Live stream={stream} />
          ) : previewAt !== undefined && take?.video ? (
            <ScrubVideo src={take.video.url} time={offset + previewAt} zoom={zoom} />
          ) : (
            <img className="ep-presenter-image" src={portraitUrl(view.settings?.portrait)} alt="Presenter portrait" />
          )}
        </div>
      )}
    </div>
  );
}

// A silent visual sampled against the narration or recorded audio clock.
function ScrubVideo({ src, time, zoom = 1 }: { src: string; time: number; zoom?: number }) {
  const ref = useRef<HTMLVideoElement>(null);
  const sync = () => {
    const video = ref.current;
    if (video && video.readyState >= 1 && !video.seeking && Math.abs(video.currentTime - time) > 0.06)
      video.currentTime = Math.min(time, video.duration || time);
  };
  useEffect(sync, [time, src]);
  return <video ref={ref} src={src} muted playsInline preload="auto" onLoadedMetadata={sync} style={{transform: `scale(${zoom})`}} />;
}

// The camera as it is being recorded, mirrored the way a person expects to see themself.
function Live({ stream }: { stream: MediaStream }) {
  const video = useRef<HTMLVideoElement>(null);
  useEffect(() => {
    if (video.current) video.current.srcObject = stream;
  }, [stream]);
  return <video ref={video} className="ep-live" autoPlay muted playsInline />;
}

// Before a picture is built: what the plan says it shows, and the things it will hold.
function Sketch({ frame, unit }: { frame: EpisodeFrame; unit?: EpisodeUnit }) {
  const words = (frame.objects ?? [])
    .map((o) => o.words || o.what)
    .filter(Boolean)
    .slice(0, 6);
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
