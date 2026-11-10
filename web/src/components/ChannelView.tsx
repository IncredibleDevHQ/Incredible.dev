// A channel: its threads as a chat, or its tasks laid out on the canvas, and the brand its work
// wears.
import { LayoutDashboard, MessagesSquare } from "lucide-react";
import { useEffect, useRef } from "react";
import { api, type Message, type Thread } from "../api";
import { useHouse } from "../store";
import { AgentMark, Avatar, clock, FileList, FooterLine, kindTitle, StatusChip } from "../ui";
import { ChannelBrand } from "./Brand";
import { Canvas } from "./Canvas";
import { Composer } from "./Composer";
import { ChannelStart } from "./Start";

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
            <ChannelStart channel={channel} inChat />
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
            : thread.kind === "research"
              ? "Research on the canvas"
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
