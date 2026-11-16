// The microphone's level while getting ready and during the take, and which microphone and
// camera are used. The level moves with the voice, so a microphone that is dead, or the wrong
// one, is seen before the take and not after it. A click opens the choice: the microphone,
// whether the browser cleans its sound up, and the camera with the picture it gives (so a
// camera sending less than it can is seen before the take). The picks are kept on this computer.
import { Check, ChevronDown, Mic } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Popover } from "../Popover";
import { Tooltip } from "../Tooltip";
import type { DevicePick, Devices as Found, Using } from "./recorder";

// How loud the microphone is right now, drawn without a render: it rises at once and falls
// slowly, so the eye can follow it.
export function Level({ stream }: { stream: MediaStream | null }) {
  const bar = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    const track = stream?.getAudioTracks()[0];
    const Context = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!track || !Context) return;
    const context = new Context();
    const source = context.createMediaStreamSource(new MediaStream([track]));
    const analyser = context.createAnalyser();
    analyser.fftSize = 512;
    source.connect(analyser);
    void context.resume().catch(() => undefined);
    const wave = new Uint8Array(analyser.fftSize);
    let shown = 0;
    const tick = window.setInterval(() => {
      analyser.getByteTimeDomainData(wave);
      let loud = 0;
      for (const v of wave) loud = Math.max(loud, Math.abs(v - 128) / 128);
      shown = Math.max(loud, shown * 0.82);
      bar.current?.style.setProperty("--level", Math.min(1, shown * 1.6).toFixed(3));
    }, 60);
    return () => {
      window.clearInterval(tick);
      source.disconnect();
      void context.close().catch(() => undefined);
    };
  }, [stream]);
  return <span ref={bar} className="ep-level" aria-hidden="true" />;
}

export function Devices({ stream, devices, using, camera, onChoose }: { stream: MediaStream | null; devices: Found; using: Using; camera: boolean; onChoose: (pick: DevicePick) => void }) {
  const [open, setOpen] = useState(false);
  const button = useRef<HTMLButtonElement>(null);
  const cameras = camera ? devices.cameras : [];
  const mic = devices.mics.find((d) => d.deviceId === using.mic)?.label ?? "the microphone";
  const pick = (change: DevicePick) => {
    setOpen(false);
    onChoose(change);
  };
  return (
    <span className="ep-devices">
      <Tooltip content="Choose the microphone and camera" side="top">
        <button ref={button} type="button" className="btn" aria-label={`Microphone and camera. Listening to ${mic}`} aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
          <Mic />
          <Level stream={stream} />
          <ChevronDown />
        </button>
      </Tooltip>
      <Popover open={open} onClose={() => setOpen(false)} anchor={button} side="top" align="start" offset={6} width={300} className="ep-menu">
        <div role="menu" aria-label="Microphone and camera">
          <p>Microphone</p>
          {devices.mics.map((d) => (
            <button type="button" role="menuitemradio" aria-checked={d.deviceId === using.mic} key={d.deviceId} onClick={() => pick({ mic: d.deviceId })}>
              {d.label}
            </button>
          ))}
          {/* off for a microphone set up for the voice; on for one in the computer, which hears the room */}
          <button type="button" role="menuitemcheckbox" aria-checked={using.clean} onClick={() => pick({ clean: !using.clean })}>
            Clean up room noise
            {using.clean && <Check />}
          </button>
          {cameras.length > 0 && (
            <p>
              Camera
              {using.picture && (
                <small>
                  {" "}
                  · {using.picture.width} × {using.picture.height}
                  {using.picture.rate > 0 && `, ${using.picture.rate} a second`}
                </small>
              )}
            </p>
          )}
          {cameras.map((d) => (
            <button type="button" role="menuitemradio" aria-checked={d.deviceId === using.camera} key={d.deviceId} onClick={() => pick({ camera: d.deviceId })}>
              {d.label}
            </button>
          ))}
        </div>
      </Popover>
    </span>
  );
}
