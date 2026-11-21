import { useEffect, useState } from "react";
import { api } from "./api";
import { SettingsPage } from "./pages/Settings";
import { ProjectInvitation } from "./pages/ProjectInvitation";
import { VoiceTest } from "./pages/VoiceTest";
import { AuthGate, WorkspaceSkeleton } from "./components/AuthGate";
import { ChannelView } from "./components/ChannelView";
import { NewEpisode } from "./components/episode/NewEpisode";
import { EpisodeStudio } from "./components/episode/Studio";
import { FrameReview } from "./components/FrameReview";
import { PreviewDialog } from "./components/Preview";
import { Sidebar } from "./components/Sidebar";
import { ThreadPanel } from "./components/ThreadPanel";
import { Viewer } from "./components/Viewer";
import { connectLive } from "./live";
import { Brand, Computer, NeedsYou, ReadBrand, Skills } from "./pages/Pages";
import { Production } from "./pages/Production";
import { followAddress, go, parse } from "./route";
import { useHouse } from "./store";
import { clock } from "./ui";

export function App() {
  const voiceTest = /^\/c\/[^/]+\/episode\/(ep_[a-z0-9]+)\/voice-test\/?$/.exec(location.pathname);
  const invite = /^\/invite\/([0-9a-f]{32})\/?$/.exec(location.pathname)?.[1];
  if (invite) return <AuthGate invite={invite}><ProjectInvitation id={invite} /></AuthGate>;
  return <AuthGate>{voiceTest ? <VoiceTest episode={voiceTest[1]} /> : <WorkspaceApp />}</AuthGate>;
}

function WorkspaceApp() {
  const [ready, setReady] = useState(false);
  const [failure, setFailure] = useState("");
  const page = useHouse((s) => s.page);
  const toast = useHouse((s) => s.toast);
  const cut = useHouse((s) => s.cut);
  const frameId = useHouse((s) => s.frameId);
  const episodeId = useHouse((s) => s.episodeId);
  const startingEpisode = useHouse((s) => s.startingEpisode);

  useEffect(() => {
    let active = true;
    const stop = followAddress();
    void useHouse
      .getState()
      .boot()
      .then(() => { if (active) { go(parse(location.pathname, location.search)); setReady(true); } })
      .catch(error => { if (active) setFailure(error instanceof Error ? error.message : "Your workspace couldn’t connect."); });
    const live = connectLive();
    return () => {
      active = false;
      stop();
      live();
    };
  }, []);

  const authenticated = useHouse(s=>s.session?.authenticated);
  const mode = useHouse(s=>s.mode);
  const channel = useHouse(s=>s.channelId);
  useEffect(()=>{
    if (!authenticated) return;
    const themeChanged=()=>{void api.logInteraction("Change theme").catch(()=>{});};
    window.addEventListener("house:theme-picked",themeChanged);
    return ()=>window.removeEventListener("house:theme-picked",themeChanged);
  },[authenticated]);
  useEffect(()=>{
    if (ready && authenticated) void api.logInteraction("View "+(page==="channel" ? episodeId ? "episode" : mode==="canvas" ? "canvas" : "channel" : page)).catch(()=>{});
  },[ready,authenticated,page,episodeId,mode,channel]);

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
          {(page === "logs" || page === "profile" || page === "settings" || page === "usage" || page === "organization") && <SettingsPage tab={page} />}
          {page === "needs" && <NeedsYou />}
          {page === "production" && <Production />}
          {page === "brand" && <Brand />}
          {page === "read-brand" && <ReadBrand />}
          {page === "skills" && <Skills />}
          {page === "computer" && <Computer />}
        </main>
      )}
      {page === "channel" && <ThreadPanel />}
      {frameId && <FrameReview />}
      {episodeId && !startingEpisode && <EpisodeStudio />}
      {startingEpisode && <NewEpisode start={startingEpisode} />}
      <PreviewDialog />
      <Viewer />
      {cut !== null && (
        <div className="house-cut" role="status">
          Out of touch with the house since {clock(cut)}. This page may be out of date until it is back.
        </div>
      )}
      {toast && (
        <div className="toast" role="status">
          {toast}
        </div>
      )}
    </div>
  );
}
