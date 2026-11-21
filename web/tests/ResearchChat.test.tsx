// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { api, type CanvasTask, type Conversation, type ConversationRow, type ResearchView } from "../src/api";
import { EMPTY_RESEARCH, ResearchColumns } from "../src/components/Research";
import { useHouse } from "../src/store";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });
function openCard(conversations: Conversation[] = [], material: Partial<ResearchView> = {}) {
  const openThread = vi.fn().mockResolvedValue(undefined);
  useHouse.setState({...useHouse.getInitialState(), openThread, research:{
    models:{codex:[{id:"sample",name:"Sample",efforts:["low","medium"]}]},repos:[],
    harnesses:[{id:"codex",title:"Codex",ready:true},{id:"claude",title:"Claude",ready:true}],
  }});
  render(<ResearchColumns task={{thread:{id:"frame"}} as CanvasTask}
    research={{...EMPTY_RESEARCH,conversations,repo:{name:"studio",path:"studio",branch:"main"},repos:["studio","team/api"],
      source_notes:"Planning notes",harness:"codex",model:"sample",effort:"medium",...material}}
    onHot={() => {}} onMake={() => {}} making={false} />);
  const card = within(screen.getByRole("article",{name:"Research chat"}));
  return {card, input:card.getByRole<HTMLTextAreaElement>("textbox",{name:"Ask a question"}), openThread};
}

test("send opens the new conversation, retains settings and ignores repeat sends", async () => {
  const pending = Promise.withResolvers<ConversationRow>();
  const ask = vi.spyOn(api,"ask").mockReturnValue(pending.promise);
  const {card,input,openThread} = openCard();
  expect(card.queryByRole("combobox")).toBeNull();
  expect(card.getByText("Planning notes")).toBeTruthy();
  const send = card.getByRole("button",{name:"Send question"});
  expect(send.hasAttribute("disabled")).toBe(true);
  fireEvent.change(input,{target:{value:"Compare the two projects"}});
  fireEvent.keyDown(input,{key:"Enter",shiftKey:true});
  fireEvent.keyDown(input,{key:"Enter",isComposing:true});
  expect(ask).not.toHaveBeenCalled();
  fireEvent.keyDown(input,{key:"Enter"});
  expect(send.hasAttribute("disabled")).toBe(true);
  fireEvent.click(send);
  expect(ask).toHaveBeenCalledTimes(1);
  expect(ask).toHaveBeenCalledWith("frame",{question:"Compare the two projects",harness:"codex",model:"sample",effort:"medium"});
  await act(async () => pending.resolve({id:"new-thread"} as ConversationRow));
  expect(openThread).toHaveBeenCalledWith("new-thread");
  expect(input.value).toBe("");
});

test("the chat keeps its draft on failure and lets the user change agent before retrying", async () => {
  const ask = vi.spyOn(api,"ask").mockRejectedValueOnce(new Error("Offline")).mockResolvedValue({id:"retry"} as ConversationRow);
  const {card,input} = openCard();
  const settings = card.getByRole("button",{name:"Research settings"});
  fireEvent.click(settings);
  expect(card.getByRole("combobox",{name:/Effort/})).toBeTruthy();
  fireEvent.click(card.getByRole("radio",{name:"Claude"}));
  fireEvent.click(settings);
  fireEvent.change(input,{target:{value:"Where do I start?"}});
  const send = card.getByRole("button",{name:"Send question"});
  fireEvent.click(send);
  expect((await card.findByRole("alert")).textContent).toBe("Offline");
  expect(input.value).toBe("Where do I start?");
  await act(async () => fireEvent.click(send));
  expect(ask).toHaveBeenLastCalledWith("frame",{question:"Where do I start?",harness:"claude",model:"",effort:""});
});

test("a recent conversation opens directly while the draft stays in the card", () => {
  const {card,input,openThread} = openCard([{id:"previous",question:"How do the projects connect?",
    harness:"codex",parent_id:"",answer:"",status:"idle",kept:0} as Conversation]);
  fireEvent.change(input,{target:{value:"An unsent question"}});
  fireEvent.click(card.getByRole("button",{name:/Recent conversation.*How do the projects connect/}));
  expect(openThread).toHaveBeenCalledWith("previous");
  expect(input.value).toBe("An unsent question");
});

test("the card lists each attachment and opens the selected file", () => {
  const files = ["brief.md", "data.csv"].map((name, i) => ({
    id: String(i), name, url: `/api/files/${i}`, size: 8, mime: "text/plain", origin: "upload",
  }));
  const source_notes = "Earlier findings\nReview <draft> for details.";
  const {card} = openCard([], {files, source_notes});
  expect(card.getByRole("region", {name:"Notes and prior research"}).textContent).toBe(source_notes);
  for (const file of files) {
    fireEvent.click(card.getByRole("button", {name:file.name}));
    expect(useHouse.getState().viewing).toEqual({files, at:file.id, title:"Research files"});
  }
});

test("older briefs with no attachments or notes only show the repository section", () => {
  const {card} = openCard([], {files:undefined, source_notes:undefined, repos:undefined});
  expect(card.getByRole("heading", {name:"Repositories"})).toBeTruthy();
  expect(card.getByText("studio")).toBeTruthy();
  expect(card.queryByRole("heading", {name:"Attached files"})).toBeNull();
  expect(card.queryByRole("heading", {name:"Notes and prior research"})).toBeNull();
});
