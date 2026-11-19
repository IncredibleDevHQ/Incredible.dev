// Recording a chapter in the browser: the camera and microphone (the microphone alone when
// nobody is on screen), one take for the whole chapter, and a mark each time the person moves to
// the next line. The marks are what let the film cut the take by line and land each picture's
// cues on the words as they were actually said. Which camera and microphone are used is the
// person's pick, kept on this computer; without one the browser's own choice is used.
//
// A take is the film's source. Guided takes combine the camera with decoded narration;
// manual takes capture the microphone. A microphone a person
// set up for their voice is left as it is (the film sets every take's loudness when it cuts
// it); and the picture is encoded well above a call's rate, since it is encoded again.
import type { NarrationGuide } from "./narrationGuide";
import { useCallback, useEffect, useRef, useState } from "react";

export type Mark = { frame: string; t: number };
export type RecorderState = "off" | "asking" | "ready" | "count" | "recording" | "review" | "saving";
export type Recording = { blob: Blob; name: string; marks: Mark[] };

export type Devices = { cameras: MediaDeviceInfo[]; mics: MediaDeviceInfo[] };
// `clean`: the browser takes the room's noise out of the sound and evens its level. Unsaid, it
// goes by the microphone's kind.
export type DevicePick = { camera?: string; mic?: string; clean?: boolean };
// What is open now: the devices, whether the sound is cleaned up, and the picture as the camera gives it.
export type Using = { camera?: string; mic?: string; clean: boolean; picture?: { width: number; height: number; rate: number } };

const PICKED = "episode-devices";
function pickedBefore(): DevicePick {
  try {
    return JSON.parse(localStorage.getItem(PICKED) ?? "{}") as DevicePick;
  } catch {
    return {};
  }
}

// H.264 first: the computer's own chip encodes it, so a full frame at a high rate drops no
// frames, where VP9 is worked out in software as the take runs. The sound is Opus wherever the
// browser offers it.
const TYPES = [
  "video/webm;codecs=avc1.640028,opus",
  "video/webm;codecs=h264,opus",
  "video/mp4;codecs=avc1.640028,mp4a.40.2",
  "video/webm;codecs=vp9,opus",
  "video/webm;codecs=vp8,opus",
  "video/webm",
  "video/mp4",
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/mp4",
];
const SOUND_BITS = 256_000;
// A quarter of a bit for each pixel of each frame: 15.6 Mbit/s for 1080p at 30 a second, about
// 115 MB a minute. A call or a stream uses a third of that, and it shows once the take is
// encoded a second time.
function pictureBits(stream: MediaStream): number {
  const { width = 1280, height = 720, frameRate = 30 } = stream.getVideoTracks()[0]?.getSettings() ?? {};
  return Math.round(Math.min(24_000_000, Math.max(4_000_000, width * height * Math.min(frameRate, 30) * 0.25)));
}

export function createRecorder(source: MediaStream, camera: boolean) {
  const type = TYPES.filter((t) => camera || t.startsWith("audio")).find((t) => MediaRecorder.isTypeSupported(t));
  return new MediaRecorder(source, { ...(type ? { mimeType: type } : {}), audioBitsPerSecond: SOUND_BITS, ...(camera ? { videoBitsPerSecond: pictureBits(source) } : {}) });
}

// A microphone that sits in the computer, its screen or its webcam hears the room and the fan
// with the voice, so its sound is cleaned up unless the person says otherwise. One they set up
// for their voice is recorded as it is.
const inTheComputer = (label: string) => /built-?in|internal|macbook|imac|display|array|webcam|facetime/i.test(label);

export function useRecorder({ frames, camera, onDone }: { frames: string[]; camera: boolean; onDone: (recording: Recording) => Promise<void> }) {
  const [state, setState] = useState<RecorderState>("off");
  const [stream, setStream] = useState<MediaStream | null>(null);
  const [index, setIndex] = useState(0);
  const [count, setCount] = useState(0);
  const [elapsed, setElapsed] = useState(0);
  const [problem, setProblem] = useState("");
  const [devices, setDevices] = useState<Devices>({ cameras: [], mics: [] });
  const [picked, setPicked] = useState<DevicePick>(pickedBefore);
  const recorder = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);
  const marks = useRef<Mark[]>([]);
  const began = useRef(0);
  const live = useRef<MediaStream | null>(null);
  const deviceRequest = useRef(0);
  const kept = useRef(true);
  const guide = useRef<NarrationGuide | null>(null);
  const [lineElapsed, setLineElapsed] = useState(0);
  const pending = useRef<Recording | null>(null);
  const reviewObjectUrl = useRef<string | null>(null);
  const [reviewUrl, setReviewUrl] = useState<string | null>(null);
  const saving = useRef(false);
  const clearReview = useCallback(() => {
    if (reviewObjectUrl.current) URL.revokeObjectURL(reviewObjectUrl.current);
    reviewObjectUrl.current = null;
    pending.current = null;
    setReviewUrl(null);
  }, []);
  const save = useCallback(async () => {
    if (!pending.current || saving.current) return;
    saving.current = true;
    setProblem("");
    setState("saving");
    try {
      await onDone(pending.current);
      clearReview();
      setState("off");
    } catch (error) {
      setProblem(error instanceof Error ? error.message : "The take could not be saved. Please try again.");
      setState("review");
    } finally { saving.current = false; }
  }, [onDone, clearReview]);

  const release = useCallback(() => {
    live.current?.getTracks().forEach((t) => t.stop());
    live.current = null;
    setStream(null);
  }, []);

  // What can be picked from. The browser names its devices only once it may use them, so the
  // list is read after the stream opens, and again when something is plugged in or pulled out.
  const list = useCallback(async () => {
    const all = await navigator.mediaDevices.enumerateDevices();
    const named = (kind: MediaDeviceKind) => all.filter((d) => d.kind === kind && d.deviceId && d.label);
    setDevices({ cameras: named("videoinput"), mics: named("audioinput") });
  }, []);
  useEffect(() => {
    if (state === "off" || !navigator.mediaDevices?.addEventListener) return;
    const changed = () => void list();
    navigator.mediaDevices.addEventListener("devicechange", changed);
    return () => navigator.mediaDevices.removeEventListener("devicechange", changed);
  }, [state, list]);

  const open = useCallback(
    async (want: DevicePick) => {
      const ask = (clean: boolean) =>
        navigator.mediaDevices.getUserMedia({
          // one channel: a voice is one, and a microphone on one input of two would otherwise be heard on one side
          audio: { echoCancellation: false, noiseSuppression: clean, autoGainControl: clean, channelCount: { ideal: 1 }, ...(want.mic ? { deviceId: { exact: want.mic } } : {}) },
          video: camera ? { width: { ideal: 1920 }, height: { ideal: 1080 }, frameRate: { ideal: 30 }, ...(want.camera ? { deviceId: { exact: want.camera } } : {}) } : false,
        });
      if (want.clean !== undefined) return ask(want.clean);
      // Not said: by the microphone's kind. Its name is certain only once it is open, so it is
      // opened on a guess from the list and opened again only when the guess was wrong.
      const mics = (await navigator.mediaDevices.enumerateDevices().catch(() => [])).filter((d) => d.kind === "audioinput");
      const guess = inTheComputer((want.mic ? mics.find((d) => d.deviceId === want.mic) : mics[0])?.label ?? "");
      const got = await ask(guess);
      const right = inTheComputer(got.getAudioTracks()[0]?.label ?? "");
      if (right === guess) return got;
      got.getTracks().forEach((t) => t.stop());
      return ask(right);
    },
    [camera],
  );

  // The camera and microphone, asked for once the person chooses to record.
  const arm = useCallback(
    async (want: DevicePick = picked) => {
      if (saving.current) return;
      const request = ++deviceRequest.current;
      clearReview();
      setProblem("");
      setState((was) => (was === "ready" ? was : "asking"));
      try {
        if (!navigator.mediaDevices?.getUserMedia) throw new Error("This browser can't record. Bring a recording as a file instead.");
        let got: MediaStream;
        try {
          got = await open(want);
        } catch (error) {
          // the one picked before is not plugged in today: the browser's own choice, then
          if (!["OverconstrainedError", "NotFoundError"].includes((error as Error).name) || !(want.camera || want.mic)) throw error;
          if (request !== deviceRequest.current) return;
          const rest: DevicePick = want.clean === undefined ? {} : { clean: want.clean };
          got = await open(rest);
          if (request === deviceRequest.current) {
            setPicked(rest);
            try {
              localStorage.setItem(PICKED, JSON.stringify(rest));
            } catch {
              // nothing was kept
            }
          }
        }
        if (request !== deviceRequest.current) {
          got.getTracks().forEach((track) => track.stop());
          return;
        }
        live.current?.getTracks().forEach((t) => t.stop());
        live.current = got;
        setStream(got);
        setIndex(0);
        setElapsed(0);
        setLineElapsed(0);
        setState("ready");
        void list();
      } catch (error) {
        if (request !== deviceRequest.current) return;
        const named = (error as Error).name;
        setProblem(
          named === "NotAllowedError"
            ? "The browser didn't allow the camera and microphone. Allow them for this page (the camera icon in the address bar), or bring a recording as a file."
            : named === "NotFoundError"
              ? "No camera or microphone was found. Bring a recording as a file instead."
              : (error as Error).message,
        );
        release();
        setState("off");
      }
    },
    [open, picked, list, release, clearReview],
  );

  // Another camera or microphone, or the sound cleaned up or left as it is: kept for next
  // time, and opened at once while getting ready. Another microphone goes back to what suits it.
  const choose = useCallback(
    (change: DevicePick) => {
      const want = { ...picked, ...change };
      if (change.mic && change.mic !== picked.mic && change.clean === undefined) delete want.clean;
      setPicked(want);
      try {
        localStorage.setItem(PICKED, JSON.stringify(want));
      } catch {
        // kept for this visit only
      }
      if (state === "ready") void arm(want);
    },
    [picked, state, arm],
  );

  const begin = useCallback(() => {
    const source = live.current;
    if (!source) return;
    const capture = guide.current ? new MediaStream([...source.getVideoTracks(), ...guide.current.stream.getAudioTracks()]) : source;
    let made: MediaRecorder;
    try { made = createRecorder(capture, camera); }
    catch (error) {
      guide.current?.stop();
      guide.current = null;
      setProblem(error instanceof Error ? error.message : "Could not start recording.");
      setState("ready");
      return;
    }
    chunks.current = [];
    let offset = 0;
    marks.current = guide.current ? frames.map((frame, i) => {
      const mark = { frame, t: offset };
      offset += guide.current!.durations[i];
      return mark;
    }) : [{ frame: frames[0], t: 0 }];
    kept.current = true;
    made.ondataavailable = (e) => e.data.size > 0 && chunks.current.push(e.data);
    made.onstop = () => {
      const duration = (performance.now() - began.current) / 1000;
      marks.current = marks.current.filter(mark => mark.t < duration);
      const blob = new Blob(chunks.current, { type: made.mimeType || (camera ? "video/webm" : "audio/webm") });
      guide.current?.stop();
      guide.current = null;
      release();
      if (!kept.current || blob.size === 0) return setState("off");
      // H.264 in a WebM container is Matroska, and the browser says so
      const ext = blob.type.includes("mp4") ? "mp4" : blob.type.includes("matroska") ? "mkv" : "webm";
      pending.current = { blob, name: `take.${ext}`, marks: marks.current };
      reviewObjectUrl.current = URL.createObjectURL(blob);
      setReviewUrl(reviewObjectUrl.current);
      setState("review");
    };
    recorder.current = made;
    began.current = performance.now();
    setIndex(0);
    setElapsed(0);
    setLineElapsed(0);
    made.start(1000);
    guide.current?.start(() => { if (made.state === "recording") made.stop(); });
    setState("recording");
  }, [camera, frames, release]);

  // Three, two, one, then the take.
  const start = useCallback((narration?: NarrationGuide) => {
    if (state !== "ready") return;
    setProblem("");
    guide.current = narration ?? null;
    setCount(3);
    setState("count");
  }, [state]);
  useEffect(() => {
    if (state !== "count") return;
    if (count === 0) return begin();
    const timer = window.setTimeout(() => setCount((c) => c - 1), 1000);
    return () => window.clearTimeout(timer);
  }, [state, count, begin]);

  useEffect(() => {
    if (state !== "recording") return;
    const timer = window.setInterval(() => {
      const elapsed = (performance.now() - began.current) / 1000;
      setElapsed(elapsed);
      if (guide.current) {
        const index = marks.current.findLastIndex(mark => mark.t <= elapsed);
        setIndex(Math.max(0, index));
        setLineElapsed(elapsed - (marks.current[index]?.t ?? 0));
        if (elapsed >= guide.current.durations.reduce((sum, duration) => sum + duration, 0)) {
          if (recorder.current?.state === "recording") recorder.current.stop();
        }
      } else setLineElapsed(elapsed - (marks.current.at(-1)?.t ?? 0));
    }, 50);
    return () => window.clearInterval(timer);
  }, [state]);

  const stop = useCallback((keep: boolean) => {
    if (saving.current) return;
    deviceRequest.current += 1;
    kept.current = keep;
    if (!keep) clearReview();
    if (recorder.current && recorder.current.state !== "inactive") recorder.current.stop();
    else {
      guide.current?.stop();
      guide.current = null;
      release();
      setState("off");
    }
  }, [release, clearReview]);

  // The next line starts now; after the last one, the take ends.
  const next = useCallback(() => {
    if (state !== "recording" || guide.current) return;
    setIndex((i) => {
      if (i + 1 >= frames.length) {
        stop(true);
        return i;
      }
      marks.current.push({ frame: frames[i + 1], t: (performance.now() - began.current) / 1000 });
      return i + 1;
    });
  }, [state, frames, stop]);

  useEffect(() => () => {
    deviceRequest.current += 1;
    kept.current = false;
    if (reviewObjectUrl.current) URL.revokeObjectURL(reviewObjectUrl.current);
    if (recorder.current?.state === "recording") recorder.current.stop();
    guide.current?.stop();
    live.current?.getTracks().forEach((t) => t.stop());
  }, []);

  const armNow = useCallback(() => arm(), [arm]);
  // What is in use: the picked devices, or whichever the browser opened, and what they give.
  const heard = stream?.getAudioTracks()[0]?.getSettings();
  const seen = stream?.getVideoTracks()[0]?.getSettings();
  const using: Using = {
    camera: seen?.deviceId,
    mic: heard?.deviceId,
    clean: heard?.noiseSuppression === true,
    picture: seen?.width && seen.height ? { width: seen.width, height: seen.height, rate: Math.round(seen.frameRate ?? 0) } : undefined,
  };
  return { state, stream, reviewUrl, save, index, count, elapsed, lineElapsed, problem, devices, using, choose, arm: armNow, start, next, stop, clearProblem: () => setProblem("") };
}
