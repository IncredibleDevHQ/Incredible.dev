// The microphone's level while getting ready and during the take, and which microphone and
// camera are used. The level moves with the voice, so a microphone that is dead, or the wrong
// one, is seen before the take and not after it. Each has a button with its name, which opens
// the choice: for the microphone, also whether the browser cleans its sound up; for the camera,
// also the picture it gives. The picks are kept on this computer.
import { Check, ChevronDown, Mic, Video } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
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

// A device's name as a person knows it. The browser adds a USB id after some ("ZV-E10M2
// (054c:0de8)"), and "Default - " before the one the system itself would pick.
const listed = (label: string) => label.replace(/\s*\([0-9a-f]{4}:[0-9a-f]{4}\)$/i, "");
const named = (label: string) => listed(label).replace(/^(Default|Communications) - /, "");

// The microphone and the camera, each named on its own button: what is in use is read without
// opening anything, and a click on either opens the others to pick from.
export function Devices({ stream, devices, using, camera, onChoose }: { stream: MediaStream | null; devices: Found; using: Using; camera: boolean; onChoose: (pick: DevicePick) => void }) {
  const mic = devices.mics.find((d) => d.deviceId === using.mic);
  const lens = devices.cameras.find((d) => d.deviceId === using.camera);
  return (
    <span className="ep-devices">
      <Picker what="Microphone" name={mic ? named(mic.label) : "Microphone"} icon={<Mic />} level={<Level stream={stream} />} onChoose={onChoose}>
        {(pick) => (
          <>
            {devices.mics.map((d) => (
              <button type="button" role="menuitemradio" aria-checked={d.deviceId === using.mic} key={d.deviceId} onClick={() => pick({ mic: d.deviceId })}>
                {listed(d.label)}
              </button>
            ))}
            {/* off for a microphone set up for the voice; on for one in the computer, which hears the room */}
            <button type="button" role="menuitemcheckbox" aria-checked={using.clean} onClick={() => pick({ clean: !using.clean })}>
              Clean up room noise
              {using.clean && <Check />}
            </button>
          </>
        )}
      </Picker>
      {camera && (
        <Picker what="Camera" name={lens ? named(lens.label) : "Camera"} icon={<Video />} onChoose={onChoose}>
          {(pick) => (
            <>
              {/* what the camera is giving, so one sending less than it can is seen before the take */}
              {using.picture && (
                <p>
                  <small>
                    {using.picture.width} × {using.picture.height}
                    {using.picture.rate > 0 && `, ${using.picture.rate} a second`}
                  </small>
                </p>
              )}
              {devices.cameras.map((d) => (
                <button type="button" role="menuitemradio" aria-checked={d.deviceId === using.camera} key={d.deviceId} onClick={() => pick({ camera: d.deviceId })}>
                  {listed(d.label)}
                </button>
              ))}
            </>
          )}
        </Picker>
      )}
    </span>
  );
}

function Picker({
  what,
  name,
  icon,
  level,
  onChoose,
  children,
}: {
  what: "Microphone" | "Camera";
  name: string;
  icon: ReactNode;
  level?: ReactNode;
  onChoose: (pick: DevicePick) => void;
  children: (pick: (change: DevicePick) => void) => ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const button = useRef<HTMLButtonElement>(null);
  const pick = (change: DevicePick) => {
    setOpen(false);
    onChoose(change);
  };
  return (
    <span className="ep-device">
      {/* the whole name, for one the button had to cut short */}
      <Tooltip content={`${what}: ${name}`} side="top">
        <button ref={button} type="button" className="btn" aria-label={`${what}: ${name}`} aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
          {icon}
          {level}
          <span>{name}</span>
          <ChevronDown />
        </button>
      </Tooltip>
      <Popover open={open} onClose={() => setOpen(false)} anchor={button} side="top" align="start" offset={6} width={340} className="ep-menu">
        <div role="menu" aria-label={what}>
          {children(pick)}
        </div>
      </Popover>
    </span>
  );
}
