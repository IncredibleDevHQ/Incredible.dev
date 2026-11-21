// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { api } from "../src/api";
import { ChannelStart } from "../src/components/Start";
import { useHouse } from "../src/store";

const channel = { id: "brand", name: "brand", topic: "", created_at: 0 };
function openChannel(authenticated: boolean) {
  useHouse.setState({ ...useHouse.getInitialState(), session: {
    authenticated, me: "member", people: [], agent: { mark: "house", model: "" }, demo: false, sandbox: null,
  } });
  return render(<ChannelStart channel={channel} />);
}

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

test.each([{}, { models: {} }])("private research opens and stays usable with empty options %j", async modelOptions => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ harnesses: [], repos: [], ...modelOptions })));
  openChannel(true);
  const trigger = screen.getByRole("button", {name: "Start research"});
  fireEvent.click(trigger);
  const dialog = within(screen.getByRole("dialog", {name: "Research a repository"}));
  fireEvent.click(dialog.getByLabelText("Find a repository"));
  expect(await dialog.findByText("Repository research is unavailable in private workspaces.")).toBeTruthy();
  const search = dialog.getByLabelText("Find a repository");
  fireEvent.change(search, {target: {value: "/sample"}});
  fireEvent.keyDown(search, {key: "Enter"});
  fireEvent.change(dialog.getByLabelText("The first question"), {target: {value: "What does it do?"}});
  expect(dialog.queryByRole("option")).toBeNull();
  expect(dialog.getByRole("button", {name: "Start research"}).hasAttribute("disabled")).toBe(true);
  fireEvent.keyDown(search, {key: "Escape"});
  expect(dialog.queryByRole("listbox")).toBeNull();
  fireEvent.keyDown(search, {key: "Escape"});
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(trigger.getAttribute("aria-expanded")).toBe("false");
});

test("a repository lookup failure leaves the picker open with an error", async () => {
  vi.spyOn(api, "researchOptions").mockRejectedValue(new Error("Offline"));
  openChannel(false);
  fireEvent.click(screen.getByRole("button", {name: "Start research"}));
  fireEvent.click(screen.getByLabelText("Find a repository"));
  expect((await screen.findByRole("alert")).textContent).toBe("Couldn’t load repositories.");
});

test("local channels can open research and load repositories even with no model choices", async () => {
  vi.spyOn(api, "researchOptions").mockResolvedValue({
    harnesses: [{ id: "claude", title: "Claude Code", ready: true }], models: {},
    repos: [{ name: "Sample", path: "/sample", branch: "main" }],
  });
  openChannel(false);
  fireEvent.click(screen.getByRole("button", {name: "Start research"}));
  const input = screen.getByLabelText("Find a repository");
  expect(input.getAttribute("aria-expanded")).toBe("false");
  expect(screen.queryByRole("listbox")).toBeNull();
  fireEvent.keyDown(input, {key: "ArrowDown"});
  expect(await screen.findByRole("option", {name: /Sample/})).toBeTruthy();
});

test("private discovery filters suggestions and completes the highlighted repository", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({
    discovery_only: true, harnesses: [], models: {},
    repos: ["studio", "studio-web", "tools"].map(name => ({ name, path: name, branch: "" })),
  })));
  openChannel(true);
  fireEvent.click(screen.getByRole("button", {name: "Start research"}));
  fireEvent.click(screen.getByLabelText("Find a repository"));
  await screen.findByRole("option", {name: "studio-web"});
  const input = screen.getByRole("combobox", {name: "Find a repository"}) as HTMLInputElement;
  fireEvent.change(input, {target: {value: "STU"}});
  expect(screen.getAllByRole("option")).toHaveLength(2);
  fireEvent.keyDown(input, {key: "ArrowDown"});
  fireEvent.keyDown(input, {key: "Enter"});
  expect(input.getAttribute("aria-expanded")).toBe("false");
  expect(screen.getByRole("button", {name: "Remove studio-web"})).toBeTruthy();
  fireEvent.change(input, {target: {value: "missing"}});
  expect(screen.getByText("No matching repositories.")).toBeTruthy();
  expect(screen.queryByRole("option")).toBeNull();
});

test("builds one run with multiple repositories, agent, notes and files", async () => {
  vi.spyOn(api, "researchOptions").mockResolvedValue({
    harnesses: ["claude","codex","kimi"].map(id => ({id, title: id === "codex" ? "Codex" : id, ready:true})) as Awaited<ReturnType<typeof api.researchOptions>>["harnesses"],
    models: {}, repos: ["alpha","beta"].map(name => ({name,path:name,branch:""})),
  });
  const run = vi.spyOn(api, "openResearch").mockRejectedValue(new Error("Try again"));
  const upload = vi.spyOn(api, "upload").mockResolvedValue([{id:"file-1",name:"analysis.md",mime:"text/markdown",size:4,url:"/api/files/file-1",origin:"upload"}]);
  openChannel(true);
  fireEvent.click(screen.getByRole("button", {name:"Start research"}));
  const dialog = within(screen.getByRole("dialog"));
  fireEvent.click(dialog.getByLabelText("Find a repository"));
  fireEvent.click(await dialog.findByRole("option", {name:"alpha"}));
  expect(dialog.queryByRole("listbox")).toBeNull();
  fireEvent.click(dialog.getByRole("combobox", {name:"Find a repository"}));
  fireEvent.click(dialog.getByRole("option", {name:"beta"}));
  expect(dialog.queryByRole("listbox")).toBeNull();
  fireEvent.click(dialog.getByRole("radio", {name:"Codex"}));
  fireEvent.change(dialog.getByLabelText("The first question"), {target:{value:"Compare the projects"}});
  fireEvent.change(dialog.getByLabelText("Notes and prior research"), {target:{value:"Earlier work covered setup."}});
  fireEvent.change(dialog.getByLabelText("Attach research files"), {target:{files:[new File(["data"],"analysis.md")]}});
  await dialog.findByRole("button",{name:"Remove analysis.md"});
  fireEvent.click(dialog.getByRole("button",{name:"Start research"}));
  await vi.waitFor(() => expect(run).toHaveBeenCalledWith("brand",expect.objectContaining({
    repos:["alpha","beta"], harness:"codex", notes:"Earlier work covered setup.", files:["file-1"],
  })));
  expect(upload).toHaveBeenCalledTimes(1);
  expect(dialog.getByRole("button",{name:"Remove alpha"})).toBeTruthy();
});
