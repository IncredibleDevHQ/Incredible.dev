// A channel: its threads as a chat, or its tasks laid out on the canvas, and the brand its work
// wears.
import { Check, Globe, LayoutDashboard, MessagesSquare, Palette } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api, type Channel, type Message, type Thread } from "../api";
import { useHouse } from "../store";
import { AgentMark, Avatar, clock, FileList, FooterLine, kindTitle, StatusChip } from "../ui";
import { Canvas } from "./Canvas";
import { Composer } from "./Composer";

export function ChannelView() {
  const { channelId, channels, mode, roots } = useHouse();
  const setMode = useHouse((s) => s.setMode);
  const channel = channels.find((c) => c.id === channelId);
  const list = channelId ? roots[channelId] ?? [] : [];
  const feed = useRef<HTMLDivElement>(null);

  useEffect(() => {
    feed.current?.scrollTo({ top: feed.current.scrollHeight });
  }, [list.length, channelId]);

  if (!channel) return <div className="empty">Pick a channel.</div>;

  return (
    <section className="main" aria-label={`#${channel.name}`}>
      <header className="bar">
        <h1>#{channel.name}</h1>
        <p>{channel.topic}</p>
        <ChannelBrand channel={channel} />
        <div className="seg" role="group" aria-label="View">
          <button type="button" aria-pressed={mode === "chat"} onClick={() => setMode("chat")}>
            <MessagesSquare />
            Chat
          </button>
          <button type="button" aria-pressed={mode === "canvas"} onClick={() => setMode("canvas")}>
            <LayoutDashboard />
            Canvas
          </button>
        </div>
      </header>
      {mode === "canvas" ? (
        <Canvas channelId={channel.id} />
      ) : (
        <div className="feed" ref={feed}>
          {list.length === 0 ? (
            <div className="empty">
              <h2>Nothing here yet</h2>
              <p>Ask the agent for something and attach what you have: a post, a deck, a recording, your notes. It works in a thread of its own, and its boards land on this channel's canvas.</p>
            </div>
          ) : (
            list.map((m) => <Root key={m.id} message={m} />)
          )}
        </div>
      )}
      {mode === "chat" && (
        <Composer
          placeholder={`Ask the agent in #${channel.name}. Attach what you have.`}
          agentLabel="Ask the agent"
          kinds
          onSend={async (body) => {
            const message = await api.startThread(channel.id, body);
            if (body.to_agent) await useHouse.getState().openThread(message.thread_id);
          }}
        />
      )}
    </section>
  );
}

function Root({ message }: { message: Message }) {
  const { people, threads, replies, turns, details } = useHouse();
  const openThread = useHouse((s) => s.openThread);
  const author = people[message.author_id];
  const thread: Thread | undefined = threads[message.thread_id];
  const count = replies[message.thread_id] ?? 0;
  return (
    <article className="msg">
      <Avatar person={author} />
      <div className="msg-body">
        <div className="msg-head">
          <strong>{author?.name ?? "Someone"}</strong>
          <time>{clock(message.created_at)}</time>
          {thread?.kind && <span className="chip">{kindTitle(thread.kind)}</span>}
        </div>
        <p className="msg-text">{message.text}</p>
        <FileList files={message.data.files} />
        {thread?.task ? (
          <TaskCard thread={thread} turn={turns[thread.id]} replies={count} thumbs={latestFrames(details[thread.id])} onOpen={() => openThread(thread.id)} />
        ) : count > 0 ? (
          <button type="button" className="linkish" onClick={() => openThread(message.thread_id)}>
            {count} {count === 1 ? "reply" : "replies"}
          </button>
        ) : null}
      </div>
    </article>
  );
}

function latestFrames(detail?: { boards: { frames: { versions: { url: string }[] }[] }[]; files: { mime: string; url: string }[] }) {
  if (!detail) return [];
  const board = detail.boards[detail.boards.length - 1];
  if (board) return board.frames.slice(0, 4).map((f) => f.versions[f.versions.length - 1]?.url).filter(Boolean) as string[];
  return detail.files.filter((f) => f.mime.startsWith("image/")).slice(0, 4).map((f) => f.url);
}

function TaskCard({ thread, turn, replies, thumbs, onOpen }: { thread: Thread; turn?: Message; replies: number; thumbs: string[]; onOpen: () => void }) {
  const mark = useHouse((s) => s.session?.agent.mark);
  const now =
    thread.status === "working"
      ? turn?.data.header && turn.data.state === "working"
        ? turn.data.header
        : "Working in the background"
      : thread.status === "needs_you"
        ? "Waiting for your review on the canvas"
        : thread.status === "failed"
          ? "Stopped before finishing"
          : turn
            ? "Done"
            : "Starting";
  return (
    <div className="task">
      <div className="task-row">
        <AgentMark mark={mark} size="sm" />
        <span className="task-now">{now}</span>
        <StatusChip status={thread.status} />
      </div>
      {thumbs.length > 0 && (
        <div className="task-thumbs">
          {thumbs.map((src) => (
            <img key={src} src={src} alt="" />
          ))}
        </div>
      )}
      <div className="task-row">
        <FooterLine footer={thread.footer} />
        <button type="button" className="linkish" style={{ marginLeft: "auto" }} onClick={onOpen}>
          Open thread{replies ? ` · ${replies} ${replies === 1 ? "reply" : "replies"}` : ""}
        </button>
      </div>
    </div>
  );
}

// The brand this channel's work wears, and a way to change it.
function ChannelBrand({ channel }: { channel: Channel }) {
  const brands = useHouse((s) => s.brands);
  const loadBrands = useHouse((s) => s.loadBrands);
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  useEffect(() => {
    if (!brands.length) void loadBrands().catch(() => undefined);
  }, [brands.length, loadBrands]);
  const worn = brands.find((b) => b.slug === (channel.brand || "default"));
  return (
    <>
      <button
        type="button"
        className="chip brand-chip"
        aria-expanded={Boolean(anchor)}
        title="The brand this channel's work wears"
        onClick={(e) => setAnchor(anchor ? null : e.currentTarget)}
      >
        {worn?.logo ? <img src={worn.logo} alt="" /> : <Palette />}
        {worn?.name ?? "Brand"}
      </button>
      {anchor && <BrandMenu channel={channel} anchor={anchor} onClose={() => setAnchor(null)} />}
    </>
  );
}

function BrandMenu({ channel, anchor, onClose }: { channel: Channel; anchor: HTMLElement; onClose: () => void }) {
  const brands = useHouse((s) => s.brands);
  const openPage = useHouse((s) => s.openPage);
  const box = useRef<HTMLDivElement>(null);
  const [place, setPlace] = useState<{ top: number; left: number } | null>(null);
  useLayoutEffect(() => {
    const r = anchor.getBoundingClientRect();
    setPlace({ top: r.bottom + 6, left: Math.max(12, Math.min(window.innerWidth - 300, r.left)) });
  }, [anchor]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    const onDown = (e: PointerEvent) => {
      if (!box.current?.contains(e.target as Node) && !anchor.contains(e.target as Node)) onClose();
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("pointerdown", onDown);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("pointerdown", onDown);
    };
  }, [anchor, onClose]);
  const wear = async (slug: string) => {
    try {
      await api.wearBrand(channel.id, slug);
      await useHouse.getState().loadBrands();
      onClose();
    } catch (error) {
      useHouse.getState().say((error as Error).message);
    }
  };
  return createPortal(
    <div className="pop brand-menu" ref={box} role="dialog" aria-label={`The brand #${channel.name} wears`} style={place ? place : { visibility: "hidden", top: 0, left: 0 }}>
      <h3>#{channel.name} wears</h3>
      <div className="pop-list" role="radiogroup">
        {brands.map((b) => (
          <button type="button" role="radio" key={b.slug} aria-checked={(channel.brand || "default") === b.slug} onClick={() => void wear(b.slug)}>
            {(channel.brand || "default") === b.slug ? <Check size={16} /> : <Palette size={16} />}
            <span>
              <b>{b.name}</b>
              <small>{b.source ? `From ${b.source.replace(/^https?:\/\//, "").split("/")[0]}` : "The configured pack"}</small>
            </span>
          </button>
        ))}
        <button
          type="button"
          onClick={() => {
            onClose();
            openPage("brand");
          }}
        >
          <Globe size={16} />
          <span>
            <b>Read one from a website</b>
          </span>
        </button>
      </div>
    </div>,
    document.body,
  );
}
