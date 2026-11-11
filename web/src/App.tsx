import { useEffect } from "react";
import { AuthGate } from "./components/AuthGate";
import { ChannelView } from "./components/ChannelView";
import { FrameReview } from "./components/FrameReview";
import { PreviewDialog } from "./components/Preview";
import { Sidebar } from "./components/Sidebar";
import { ThreadPanel } from "./components/ThreadPanel";
import { Viewer } from "./components/Viewer";
import { connectLive } from "./live";
import { Brand, Computer, NeedsYou, Skills } from "./pages/Pages";
import { useHouse } from "./store";

export function App() {
  return <AuthGate><WorkspaceApp /></AuthGate>;
}

function WorkspaceApp() {
  const page = useHouse((s) => s.page);
  const toast = useHouse((s) => s.toast);
  const frameId = useHouse((s) => s.frameId);

  useEffect(() => {
    void useHouse.getState().boot().catch((error: Error) => useHouse.getState().say(error.message));
    return connectLive();
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
