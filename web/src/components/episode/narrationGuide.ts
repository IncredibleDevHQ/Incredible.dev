import { useEffect, useRef, useState } from "react";

export type NarrationGuide = {
  stream: MediaStream;
  durations: number[];
  start: (onEnded: () => void) => void;
  stop: () => void;
};

// Decode before the countdown so network delays cannot interrupt a camera take.
export function useNarrationGuide() {
  const current = useRef<NarrationGuide | null>(null);
  const [loading, setLoading] = useState(false);
  const [problem, setProblem] = useState("");
  const dispose = () => { current.current?.stop(); current.current = null; };
  useEffect(() => dispose, []);
  const prepare = async (urls: string[]): Promise<NarrationGuide | null> => {
    dispose();
    setLoading(true);
    setProblem("");
    const context = new AudioContext();
    try {
      await context.resume();
      const buffers = await Promise.all(urls.map(async url => {
        const response = await fetch(url);
        if (!response.ok) throw new Error("Could not load narration. Try again.");
        return context.decodeAudioData(await response.arrayBuffer());
      }));
      const destination = context.createMediaStreamDestination();
      const sources = buffers.map(buffer => {
        const source = context.createBufferSource();
        source.buffer = buffer;
        source.connect(destination);
        source.connect(context.destination);
        return source;
      });
      let stopped = false;
      const guide: NarrationGuide = {
        stream: destination.stream,
        durations: buffers.map(buffer => buffer.duration),
        start(onEnded) {
          sources[sources.length - 1].onended = () => { if (!stopped) onEnded(); };
          let at = context.currentTime;
          sources.forEach((source, i) => { source.start(at); at += buffers[i].duration; });
        },
        stop() {
          if (stopped) return;
          stopped = true;
          sources.forEach(source => { try { source.stop(); } catch { /* not started */ } });
          destination.stream.getTracks().forEach(track => track.stop());
          void context.close();
        },
      };
      current.current = guide;
      return guide;
    } catch (error) {
      await context.close();
      setProblem(error instanceof Error ? error.message : "Could not prepare narration.");
      return null;
    } finally {
      setLoading(false);
    }
  };
  return { prepare, loading, problem };
}
