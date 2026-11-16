// A clone sample stays in memory until the person previews it and submits the form.
import { useEffect, useRef, useState } from "react";
import { createRecorder } from "./recorder";

export const MAX_SAMPLE_BYTES = 25 * 1024 * 1024;

export function useVoiceSample(onSample: (file: File) => void) {
  const [phase, setPhase] = useState<"idle" | "asking" | "recording" | "stopping">("idle");
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState("");
  const recorder = useRef<MediaRecorder | null>(null);
  const mounted = useRef(false);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      const active = recorder.current;
      if (active && active.state !== "inactive") active.stop();
      active?.stream.getTracks().forEach(track => track.stop());
    };
  }, []);
  useEffect(() => {
    if (phase !== "recording") return;
    const start = performance.now();
    const timer = window.setInterval(() => setElapsed(Math.floor((performance.now() - start) / 1000)), 250);
    return () => clearInterval(timer);
  }, [phase]);

  async function start() {
    if (phase !== "idle") return;
    setPhase("asking");
    setError("");
    setElapsed(0);
    let stream: MediaStream | undefined;
    try {
      if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
        throw new Error("Recording is unavailable in this browser. Upload an audio file instead.");
      }
      stream = await navigator.mediaDevices.getUserMedia({audio: true});
      if (!mounted.current) {
        stream.getTracks().forEach(track => track.stop());
        return;
      }
      const active = createRecorder(stream, false);
      recorder.current = active;
      const chunks: Blob[] = [];
      let size = 0;
      let failure = "";
      active.ondataavailable = ({data}) => {
        size += data.size;
        if (size <= MAX_SAMPLE_BYTES) chunks.push(data);
        else {
          failure = "The recording exceeds 25 MiB. Record a shorter sample.";
          if (active.state !== "inactive") active.stop();
        }
      };
      active.onerror = () => { failure = "Recording was interrupted. Record again or upload a file."; };
      active.onstop = () => {
        active.stream.getTracks().forEach(track => track.stop());
        recorder.current = null;
        if (!mounted.current) return;
        setPhase("idle");
        if (failure || !size) {
          setError(failure || "No audio was captured. Try recording again.");
          return;
        }
        const type = active.mimeType || chunks[0].type || "audio/webm";
        const ext = type.includes("mp4") ? "m4a" : "webm";
        onSample(new File(chunks, `voice-sample.${ext}`, {type}));
      };
      active.start(1000);
      setPhase("recording");
    } catch (cause) {
      stream?.getTracks().forEach(track => track.stop());
      recorder.current = null;
      if (!mounted.current) return;
      const e = cause as Error;
      setError(e.name === "NotAllowedError" ? "Microphone access was denied. Allow access or upload a recording." : e.message);
      setPhase("idle");
    }
  }
  function stop() {
    if (recorder.current?.state === "recording") {
      setPhase("stopping");
      recorder.current.stop();
    }
  }
  return { phase, start, stop, elapsed, error, clearError: () => setError("") };
}
