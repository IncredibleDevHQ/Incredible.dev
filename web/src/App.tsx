import { useEffect } from "react";
import { ChannelView } from "./components/ChannelView";
import { FrameReview } from "./components/FrameReview";
import { PreviewDialog } from "./components/Preview";
import { Sidebar } from "./components/Sidebar";
import { ThreadPanel } from "./components/ThreadPanel";
import { Viewer } from "./components/Viewer";
import { connectLive } from "./live";
import { Brand, Computer, NeedsYou, ReadBrand, Skills } from "./pages/Pages";
import { followAddress, go, parse } from "./route";
import { useHouse } from "./store";

export function App() {
  const page = useHouse((s) => s.page);
  const toast = useHouse((s) => s.toast);
  const frameId = useHouse((s) => s.frameId);

  useEffect(() => {
    const stop = followAddress();
    void useHouse
      .getState()
      .boot()
      .then(() => go(parse(location.pathname, location.search)))
      .catch((error: Error) => useHouse.getState().say(error.message));
    const live = connectLive();
    return () => {
      stop();
      live();
    };
  }, []);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => useHouse.getState().say(null), 4000);
    return () => window.clearTimeout(timer);
  }, [toast]);

  return (
    <div className="app">
      <Sidebar />
      {page === "channel" ? (
        <ChannelView />
      ) : (
        <main className="main">
          {page === "needs" && <NeedsYou />}
          {page === "brand" && <Brand />}
          {page === "read-brand" && <ReadBrand />}
          {page === "skills" && <Skills />}
          {page === "computer" && <Computer />}
        </main>
      )}
      {page === "channel" && <ThreadPanel />}
      {frameId && <FrameReview />}
      <PreviewDialog />
      <Viewer />
      {toast && (
        <div className="toast" role="status">
          {toast}
        </div>
      )}
    </div>
  );
}
