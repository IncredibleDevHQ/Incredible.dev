// Writing to a channel or a thread. To the agent (a task, or a follow-up to it) or to the team
// only; with files people already have, and optionally what they want back.
import { ArrowUp, Paperclip, Users, Wand2, X } from "lucide-react";
import { useRef, useState } from "react";
import { api, type FileView } from "../api";
import { useHouse } from "../store";
import { AgentMark, KindIcon, kindTitle } from "../ui";

type Props = {
  placeholder: string;
  agentLabel: string;
  kinds?: boolean;
  allowTeam?: boolean;
  // Files can come along (a research conversation's follow-up is words only).
  attach?: boolean;
  // Why sending waits, when it does; the box still takes a draft meanwhile.
  wait?: string;
  onSend: (body: { text: string; to_agent: boolean; files: string[]; kind: string }) => Promise<void>;
};

export function Composer({ placeholder, agentLabel, kinds, allowTeam = true, attach: attaches = true, wait, onSend }: Props) {
  const mark = useHouse((s) => s.session?.agent.mark);
  const capabilities = useHouse((s) => s.catalog.capabilities);
  const [text, setText] = useState("");
  const [toAgent, setToAgent] = useState(true);
  const [files, setFiles] = useState<FileView[]>([]);
  const [kind, setKind] = useState("");
  const [picking, setPicking] = useState(false);
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const area = useRef<HTMLTextAreaElement>(null);

  const grow = () => {
    const el = area.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(240, el.scrollHeight)}px`;
  };

  const attach = async (list: FileList | null) => {
    if (!list?.length) return;
    try {
      const uploaded = await api.upload(Array.from(list));
      setFiles((f) => [...f, ...uploaded]);
    } catch (error) {
      useHouse.getState().say((error as Error).message);
    }
  };

  const send = async () => {
    const words = text.trim();
    if (!words || busy || wait) return;
    setBusy(true);
    try {
      await onSend({ text: words, to_agent: toAgent, files: files.map((f) => f.id), kind: toAgent ? kind : "" });
      setText("");
      setFiles([]);
      setKind("");
      requestAnimationFrame(grow);
    } catch (error) {
      useHouse.getState().say((error as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="composer">
      <div
        className="box"
        style={{ position: "relative" }}
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          if (attaches) void attach(e.dataTransfer.files);
        }}
      >
        {picking && kinds && (
          <div className="kinds" role="dialog" aria-label="What should it make?">
            <h3>What should it make?</h3>
            <div className="kinds-grid">
              {capabilities.map((k) => (
                <button
                  type="button"
                  key={k.id}
                  aria-pressed={kind === k.id}
                  onClick={() => {
                    setKind(kind === k.id ? "" : k.id);
                    setPicking(false);
                    area.current?.focus();
                  }}
                >
                  <KindIcon kind={k.id} />
                  <span>
                    <b>{k.title}</b>
                    <small>{k.line}</small>
                  </span>
                </button>
              ))}
            </div>
          </div>
        )}
        {(files.length > 0 || kind) && (
          <div className="pending">
            {kind && (
              <span className="chip green">
                {kindTitle(kind)}
                <X role="button" aria-label="Clear" onClick={() => setKind("")} />
              </span>
            )}
            {files.map((f) => (
              <span className="chip" key={f.id}>
                {f.name}
                <X role="button" aria-label={`Remove ${f.name}`} onClick={() => setFiles(files.filter((x) => x.id !== f.id))} />
              </span>
            ))}
          </div>
        )}
        <textarea
          ref={area}
          rows={1}
          value={text}
          placeholder={wait || (toAgent ? placeholder : "Message the team. The agent won't act on it.")}
          aria-label={placeholder}
          onChange={(e) => {
            setText(e.target.value);
            grow();
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              void send();
            }
          }}
        />
        <div className="box-row">
          {allowTeam && (
            <div className="toggle" role="group" aria-label="Who it is for">
              <button type="button" aria-pressed={toAgent} onClick={() => setToAgent(true)}>
                <AgentMark mark={mark} size="sm" />
                {agentLabel}
              </button>
              <button type="button" aria-pressed={!toAgent} onClick={() => setToAgent(false)}>
                <Users size={15} />
                Team only
              </button>
            </div>
          )}
          {attaches && (
            <button type="button" className="icon-btn" aria-label="Attach files" title="Attach what you have" onClick={() => input.current?.click()}>
              <Paperclip />
            </button>
          )}
          {kinds && toAgent && (
            <button type="button" className="icon-btn" aria-label="What should it make?" title="What should it make?" aria-expanded={picking} onClick={() => setPicking(!picking)}>
              <Wand2 />
            </button>
          )}
          <input ref={input} type="file" multiple hidden onChange={(e) => void attach(e.target.files)} />
          <button type="button" className="icon-btn send" aria-label="Send" title={wait} disabled={!text.trim() || busy || Boolean(wait)} onClick={() => void send()}>
            <ArrowUp />
          </button>
        </div>
      </div>
    </div>
  );
}
