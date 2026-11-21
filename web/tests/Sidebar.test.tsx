// @vitest-environment jsdom
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Sidebar } from "../src/components/Sidebar";
import { authRequest } from "../src/components/AuthGate";
import { useHouse } from "../src/store";

vi.mock("../src/components/AuthGate", () => ({ authRequest: vi.fn() }));

const me = { id: "member", name: "member@example.com", initials: "M", hue: 152, agent: false };

beforeEach(() => {
  vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener() {}, removeEventListener() {} }));
  localStorage.clear();
  useHouse.setState({ ...useHouse.getInitialState(), people: { member: me }, session: {
    organizationName: "Pine Studio", email: me.name, me: "member", people: [me], authenticated: true, demo: false, agent: {mark: "house", model: "test"}, sandbox: null,
  } });
  vi.mocked(authRequest).mockReset();
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

test("appearance stays visible and Settings opens from the profile row", async () => {
  const user = userEvent.setup();
  render(<div id="root"><Sidebar /></div>);
  await user.click(screen.getByRole("button", { name: "Light" }));
  expect(localStorage.getItem("house:theme")).toBe("light");
  expect(screen.queryByRole("button", { name: "Settings" })).toBeNull();
  const trigger = screen.getByRole("button", { name: "Account options for member@example.com" });
  expect(within(trigger).getByText(me.name).getAttribute("title")).toBe(me.name);
  expect(trigger.querySelector(".lucide-ellipsis-vertical")).toBeTruthy();
  await user.click(trigger);
  const panel = screen.getByRole("group", { name: "Account options" });
  expect(within(panel).getAllByRole("button").map(button => button.textContent?.trim())).toEqual(["Settings", "Organization", "Usage", "Log out"]);
  expect(within(panel).queryByRole("group", { name: "Appearance" })).toBeNull();
  expect(within(panel).getByRole("button", { name: "Log out" })).toBeTruthy();
  await user.click(within(panel).getByRole("button", { name: "Settings" }));
  expect(useHouse.getState().page).toBe("settings");
  expect(trigger.getAttribute("aria-expanded")).toBe("false");
});

test("keyboard opens the panel, Tab reaches its controls and Escape restores profile focus", async () => {
  const user = userEvent.setup();
  render(<div id="root"><Sidebar /></div>);
  const trigger = screen.getByRole("button", { name: "Account options for member@example.com" });
  trigger.focus();
  await user.keyboard("{Enter}");
  await user.tab();
  expect(document.activeElement).toBe(screen.getByRole("button", { name: "Settings" }));
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("group", { name: "Account options" })).toBeNull();
  expect(document.activeElement).toBe(trigger);
});

test("clicking outside dismisses the account panel", async () => {
  const user = userEvent.setup();
  render(<div id="root"><Sidebar /></div>);
  await user.click(screen.getByRole("button", { name: "Account options for member@example.com" }));
  await user.click(screen.getByText("Creative House"));
  expect(screen.queryByRole("group", { name: "Account options" })).toBeNull();
});

test("a sign-out failure keeps the session and reports the error", async () => {
  const user = userEvent.setup();
  vi.mocked(authRequest).mockRejectedValue(new Error("Connection unavailable"));
  render(<div id="root"><Sidebar /></div>);
  await user.click(screen.getByRole("button", { name: "Account options for member@example.com" }));
  await user.click(screen.getByRole("button", { name: "Log out" }));
  expect(authRequest).toHaveBeenCalledWith("logout", {});
  expect(useHouse.getState().toast).toBe("Connection unavailable");
  expect(useHouse.getState().session?.me).toBe("member");
  expect(screen.getByRole("button", { name: "Log out" }).hasAttribute("disabled")).toBe(false);
});

test("pending sign out cannot be submitted twice", async () => {
  const user = userEvent.setup();
  vi.mocked(authRequest).mockReturnValue(new Promise(() => {}));
  render(<div id="root"><Sidebar /></div>);
  await user.click(screen.getByRole("button", { name: "Account options for member@example.com" }));
  await user.click(screen.getByRole("button", { name: "Log out" }));
  const pending = screen.getByRole("button", { name: "Logging out…" });
  expect(pending.hasAttribute("disabled")).toBe(true);
  await user.click(pending);
  expect(authRequest).toHaveBeenCalledTimes(1);
});

test("the local profile menu omits demo identities and disables logout without a login", async () => {
  const user = userEvent.setup();
  useHouse.setState({session: {...useHouse.getState().session!, authenticated: false},
    people: {member: me, teammate: {...me, id: "teammate", name: "Teammate"}}});
  render(<div id="root"><Sidebar /></div>);
  await user.click(screen.getByRole("button", {name: /Account options for/}));
  const panel = screen.getByRole("group", {name: "Account options"});
  expect(within(panel).queryByText("Teammate")).toBeNull();
  expect(within(panel).getByRole("button", {name: "Log out"}).hasAttribute("disabled")).toBe(true);
});

test("browser annotation preserves the profile menu until focus returns elsewhere in the workspace", async () => {
  const user = userEvent.setup();
  render(<><div id="root"><Sidebar /><button>Canvas action</button></div><button>Annotation toolbar</button></>);
  const trigger = screen.getByRole("button", {name: /Account options for/});
  await user.click(trigger);
  await user.click(screen.getByRole("button", {name: "Annotation toolbar"}));
  await user.keyboard("{Escape}");
  expect(trigger.getAttribute("aria-expanded")).toBe("true");
  await user.tab({shift: true});
  expect(document.activeElement).toBe(screen.getByRole("button", {name: "Canvas action"}));
  expect(trigger.getAttribute("aria-expanded")).toBe("false");
});
