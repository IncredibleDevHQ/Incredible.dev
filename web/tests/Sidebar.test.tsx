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
    me: "member", people: [me], authenticated: true, demo: false, agent: {mark: "house", model: "test"}, sandbox: null,
  } });
  vi.mocked(authRequest).mockReset();
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

test("appearance stays visible and Settings opens from the profile row", async () => {
  const user = userEvent.setup();
  render(<Sidebar />);
  await user.click(screen.getByRole("button", { name: "Light" }));
  expect(localStorage.getItem("house:theme")).toBe("light");
  expect(screen.queryByRole("button", { name: "Settings" })).toBeNull();
  const trigger = screen.getByRole("button", { name: "Account options for member@example.com" });
  await user.click(within(trigger).getByText("Private workspace"));
  const panel = screen.getByRole("group", { name: "Account options" });
  expect(within(panel).queryByRole("group", { name: "Appearance" })).toBeNull();
  expect(within(panel).getByRole("button", { name: "Sign out" })).toBeTruthy();
  await user.click(within(panel).getByRole("button", { name: "Settings" }));
  expect(useHouse.getState().page).toBe("settings");
  expect(trigger.getAttribute("aria-expanded")).toBe("false");
});

test("keyboard opens the panel, Tab reaches its controls and Escape restores profile focus", async () => {
  const user = userEvent.setup();
  render(<Sidebar />);
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
  render(<Sidebar />);
  await user.click(screen.getByRole("button", { name: "Account options for member@example.com" }));
  await user.click(screen.getByText("Creative House"));
  expect(screen.queryByRole("group", { name: "Account options" })).toBeNull();
});

test("a sign-out failure keeps the session and reports the error", async () => {
  const user = userEvent.setup();
  vi.mocked(authRequest).mockRejectedValue(new Error("Connection unavailable"));
  render(<Sidebar />);
  await user.click(screen.getByRole("button", { name: "Account options for member@example.com" }));
  await user.click(screen.getByRole("button", { name: "Sign out" }));
  expect(authRequest).toHaveBeenCalledWith("logout", {});
  expect(useHouse.getState().toast).toBe("Connection unavailable");
  expect(useHouse.getState().session?.me).toBe("member");
  expect(screen.getByRole("button", { name: "Sign out" }).hasAttribute("disabled")).toBe(false);
});

test("pending sign out cannot be submitted twice", async () => {
  const user = userEvent.setup();
  vi.mocked(authRequest).mockReturnValue(new Promise(() => {}));
  render(<Sidebar />);
  await user.click(screen.getByRole("button", { name: "Account options for member@example.com" }));
  await user.click(screen.getByRole("button", { name: "Sign out" }));
  const pending = screen.getByRole("button", { name: "Signing out…" });
  expect(pending.hasAttribute("disabled")).toBe(true);
  await user.click(pending);
  expect(authRequest).toHaveBeenCalledTimes(1);
});

test("native development retains identity switching inside the same panel", async () => {
  const user = userEvent.setup();
  const switchPerson = vi.fn().mockResolvedValue(undefined);
  useHouse.setState({ session: {...useHouse.getState().session!, authenticated: false},
    people: { member: me, teammate: {...me, id: "teammate", name: "Teammate"} }, switchPerson });
  render(<Sidebar />);
  await user.click(screen.getByRole("button", { name: "Account options for member@example.com" }));
  expect(screen.queryByRole("button", { name: "Sign out" })).toBeNull();
  await user.click(screen.getByRole("menuitemradio", { name: "Teammate" }));
  expect(switchPerson).toHaveBeenCalledWith("teammate");
  expect(screen.queryByRole("group", { name: "Account options" })).toBeNull();
});
