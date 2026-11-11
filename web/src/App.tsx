import { useEffect, useState } from "react";
import { SettingsPage } from "./pages/Settings";
import { AuthGate, WorkspaceSkeleton } from "./components/AuthGate";
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
  return <AuthGate><WorkspaceApp /></AuthGate>;
}

function WorkspaceApp() {
  const [ready, setReady] = useState(false);
  const [failure, setFailure] = useState("");
  const page = useHouse((s) => s.page);
  const toast = useHouse((s) => s.toast);
  const frameId = useHouse((s) => s.frameId);

  useEffect(() => {
    let active = true;
    const stop = followAddress();
    void useHouse
      .getState()
      .boot()
      .then(() => { if (active) { go(parse(location.pathname, location.search)); setReady(true); } })
      .catch(() => { if (active) setFailure("Your workspace couldn’t connect."); });
    const live = connectLive();
    return () => {
      active = false;
      stop();
      live();
    };
  }, []);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => useHouse.getState().say(null), 4000);
    return () => window.clearTimeout(timer);
  }, [toast]);

  if (failure) return <main className="auth-shell"><section className="auth-card"><p role="alert">{failure}</p><button className="btn" onClick={() => location.reload()}>Try again</button></section></main>;
  if (!ready) return <WorkspaceSkeleton />;
  return (
    <div className="app">
      <Sidebar />
      {page === "channel" ? (
        <ChannelView />
      ) : (
        <main className="main">
          {page === "settings" && <SettingsPage />}
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
