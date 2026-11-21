// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { api, type Note } from "../src/api";
import { ThreadPanel } from "../src/components/ThreadPanel";
import { useHouse } from "../src/store";

const note = { id: "n", text: "Research answer", message_id: "m" } as Note;

function showAnswer() {
  const state = useHouse.getInitialState();
  useHouse.setState({
    ...state, threadId: "conversation", research: {models:{},repos:[],harnesses:[]},
    details: { conversation: {
      thread: {id:"conversation", title:"Research", task:false},
      conversation: {id:"conversation", frame_id:"frame", repo:"sample", harness:"codex"},
      messages: [{id:"m", thread_id:"conversation", created_at:0, author_id:"agent", kind:"agent", text:note.text, data:{}}],
      boards:[], work:[],
    } } as typeof state.details,
    canvas: {channel:[{thread:{id:"frame"},research:{notes:[]}}]} as typeof state.canvas,
  });
  HTMLElement.prototype.scrollTo ??= () => {};
  render(<ThreadPanel />);
  return screen.getByRole("button", {name:"Keep as a note"});
}

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

test("a slow note save shows progress immediately and stays kept while the canvas catches up", async () => {
  const pending = Promise.withResolvers<Note>();
  const save = vi.spyOn(api, "keepNote").mockReturnValue(pending.promise);
  const button = showAnswer();
  fireEvent.click(button);
  expect(screen.getByRole("button", {name:"Saving…", busy:true})).toBe(button);
  expect(button.hasAttribute("disabled")).toBe(true);
  fireEvent.click(button);
  expect(save).toHaveBeenCalledTimes(1);
  expect(save).toHaveBeenCalledWith("frame",{text:note.text,conversation_id:"conversation",message_id:"m"});
  await act(async () => pending.resolve(note));
  expect(screen.getByRole("button", {name:"Kept as a note"}).hasAttribute("disabled")).toBe(true);
  const refresh = (notes: Note[]) => act(() => {
    const frame = useHouse.getState().canvas.channel[0];
    useHouse.setState({canvas:{channel:[{...frame, research:{...frame.research!, notes}}]}});
  });
  refresh([note]);
  refresh([]);
  expect(screen.getByRole("button", {name:"Keep as a note"}).hasAttribute("disabled")).toBe(false);
});

test("a failed save clears progress and lets the reader retry", async () => {
  const save = vi.spyOn(api, "keepNote").mockRejectedValueOnce(new Error("Offline")).mockResolvedValue(note);
  const button = showAnswer();
  fireEvent.click(button);
  await screen.findByRole("button", {name:"Keep as a note", busy:false});
  expect(useHouse.getState().toast).toBe("Offline");
  fireEvent.click(button);
  await screen.findByRole("button", {name:"Kept as a note"});
  expect(save).toHaveBeenCalledTimes(2);
});
