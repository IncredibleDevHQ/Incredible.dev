// Recording a chapter in the browser: the camera and microphone (the microphone alone when
// nobody is on screen), one take for the whole chapter, and a mark each time the person moves to
// the next line. The marks are what let the film cut the take by line and land each picture's
// cues on the words as they were actually said.
import { useCallback, useEffect, useRef, useState } from "react";

export type Mark = { frame: string; t: number };
export type RecorderState = "off" | "asking" | "ready" | "count" | "recording" | "saving";
export type Recording = { blob: Blob; name: string; marks: Mark[] };

const TYPES = ["video/webm;codecs=vp9,opus", "video/webm;codecs=vp8,opus", "video/webm", "video/mp4", "audio/webm;codecs=opus", "audio/webm", "audio/mp4"];

export function useRecorder({ frames, camera, onDone }: { frames: string[]; camera: boolean; onDone: (recording: Recording) => Promise<void> }) {
  const [state, setState] = useState<RecorderState>("off");
  const [stream, setStream] = useState<MediaStream | null>(null);
  const [index, setIndex] = useState(0);
  const [count, setCount] = useState(0);
  const [elapsed, setElapsed] = useState(0);
  const [problem, setProblem] = useState("");
  const recorder = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);
  const marks = useRef<Mark[]>([]);
  const began = useRef(0);
  const live = useRef<MediaStream | null>(null);
  const kept = useRef(true);

  const release = useCallback(() => {
    live.current?.getTracks().forEach((t) => t.stop());
    live.current = null;
    setStream(null);
  }, []);

  // The camera and microphone, asked for once the person chooses to record.
  const arm = useCallback(async () => {
    setProblem("");
    setState("asking");
    try {
      if (!navigator.mediaDevices?.getUserMedia) throw new Error("This browser can't record. Bring a recording as a file instead.");
      const got = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true },
        video: camera ? { width: { ideal: 1920 }, height: { ideal: 1080 }, frameRate: { ideal: 30 } } : false,
      });
      live.current = got;
      setStream(got);
      setIndex(0);
      setState("ready");
    } catch (error) {
      const named = (error as Error).name;
      setProblem(
        named === "NotAllowedError"
          ? "The browser didn't allow the camera and microphone. Allow them for this page, or bring a recording as a file."
          : named === "NotFoundError"
            ? "No camera or microphone was found. Bring a recording as a file instead."
            : (error as Error).message,
      );
      setState("off");
    }
  }, [camera]);

  const begin = useCallback(() => {
    const source = live.current;
    if (!source) return;
    const type = TYPES.filter((t) => camera || t.startsWith("audio")).find((t) => MediaRecorder.isTypeSupported(t));
    const made = new MediaRecorder(source, type ? { mimeType: type, videoBitsPerSecond: 6_000_000 } : undefined);
    chunks.current = [];
    marks.current = [{ frame: frames[0], t: 0 }];
    kept.current = true;
    made.ondataavailable = (e) => e.data.size > 0 && chunks.current.push(e.data);
    made.onstop = () => {
      const blob = new Blob(chunks.current, { type: made.mimeType || (camera ? "video/webm" : "audio/webm") });
      release();
      if (!kept.current || blob.size === 0) return setState("off");
      setState("saving");
      const ext = blob.type.includes("mp4") ? "mp4" : "webm";
      void onDone({ blob, name: `take.${ext}`, marks: marks.current })
        .catch((error: Error) => setProblem(error.message))
        .finally(() => setState("off"));
    };
    recorder.current = made;
    began.current = performance.now();
    setIndex(0);
    setElapsed(0);
    made.start(1000);
    setState("recording");
  }, [camera, frames, onDone, release]);

  // Three, two, one, then the take.
  const start = useCallback(() => {
    setCount(3);
    setState("count");
  }, []);
  useEffect(() => {
    if (state !== "count") return;
    if (count === 0) return begin();
    const timer = window.setTimeout(() => setCount((c) => c - 1), 800);
    return () => window.clearTimeout(timer);
  }, [state, count, begin]);

  useEffect(() => {
    if (state !== "recording") return;
    const timer = window.setInterval(() => setElapsed((performance.now() - began.current) / 1000), 200);
    return () => window.clearInterval(timer);
  }, [state]);

  const stop = useCallback((keep: boolean) => {
    kept.current = keep;
    if (recorder.current && recorder.current.state !== "inactive") recorder.current.stop();
    else {
      release();
      setState("off");
    }
  }, [release]);

  // The next line starts now; after the last one, the take ends.
  const next = useCallback(() => {
    if (state !== "recording") return;
    setIndex((i) => {
      if (i + 1 >= frames.length) {
        stop(true);
        return i;
      }
      marks.current.push({ frame: frames[i + 1], t: (performance.now() - began.current) / 1000 });
      return i + 1;
    });
  }, [state, frames, stop]);

  useEffect(() => () => live.current?.getTracks().forEach((t) => t.stop()), []);

  return { state, stream, index, count, elapsed, problem, arm, start, next, stop, clearProblem: () => setProblem("") };
}
