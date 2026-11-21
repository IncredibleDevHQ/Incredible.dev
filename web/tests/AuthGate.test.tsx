// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { AuthGate } from "../src/components/AuthGate";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

test("a verified reload skips provider discovery and the sign-in splash", async () => {
  const fetcher = vi.fn().mockResolvedValue(new Response("{}", {status: 200}));
  vi.stubGlobal("fetch", fetcher);
  render(<AuthGate><p>Workspace contents</p></AuthGate>);
  expect(screen.queryByText("Opening your workspace…")).toBeNull();
  expect(await screen.findByText("Workspace contents")).toBeTruthy();
  expect(fetcher.mock.calls.map(([url]) => url)).toEqual(["/api/auth/session"]);
});

test("a failed session check keeps private contents hidden", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", {status: 503})));
  render(<AuthGate><p>Private contents</p></AuthGate>);
  expect(await screen.findByRole("alert")).toBeTruthy();
  expect(screen.queryByText("Private contents")).toBeNull();
});

test.each([200, 409])("signup shows progress then opens sign-in for status %s", async status => {
  const { fireEvent } = await import("@testing-library/react");
  let resolve!: (response: Response) => void;
  vi.stubGlobal("fetch", vi.fn()
    .mockResolvedValueOnce(new Response("{}", {status: 401}))
    .mockResolvedValueOnce(Response.json({google: true}))
    .mockImplementationOnce(() => new Promise<Response>(r => {resolve = r;})));
  render(<AuthGate>Workspace</AuthGate>);
  fireEvent.click(await screen.findByRole("button", {name: "Create an account"}));
  fireEvent.change(screen.getByLabelText("Email"), {target: {value: "member@example.com"}});
  fireEvent.change(screen.getByLabelText("Password"), {target: {value: "example-password"}});
  fireEvent.click(screen.getByRole("button", {name: "Create account"}));
  const pending = await screen.findByRole("button", {name: /Creating account/});
  expect(pending.querySelector(".spin")).toBeTruthy();
  expect((pending as HTMLButtonElement).disabled).toBe(true);
  const feedback = status === 409 ? {detail:"Account already exists."} : {message:"Confirm your email."};
  resolve(Response.json(feedback, {status}));
  expect(await screen.findByRole("heading", {name:"Welcome back"})).toBeTruthy();
  expect(screen.getByRole(status === 409 ? "alert" : "status").textContent).toBe(Object.values(feedback)[0]);
  expect((screen.getByLabelText("Email or username") as HTMLInputElement).value).toBe("member@example.com");
  expect((screen.getByLabelText("Password") as HTMLInputElement).value).toBe("");
});

test("a new root account names its organization before opening a project", async () => {
  const { fireEvent } = await import("@testing-library/react");
  const fetcher = vi.fn()
    .mockResolvedValueOnce(Response.json({user:{id:"new"},root_entry:true}))
    .mockResolvedValueOnce(Response.json({needs_organization:true}))
    .mockResolvedValueOnce(Response.json({detail:"Please retry."},{status:503}));
  vi.stubGlobal("fetch",fetcher);
  render(<AuthGate>Workspace</AuthGate>);
  const name = await screen.findByLabelText("Organization name");
  fireEvent.change(name,{target:{value:"Design team"}});
  fireEvent.click(screen.getByRole("button",{name:"Open workspace"}));
  expect(await screen.findByRole("alert")).toBeTruthy();
  expect(JSON.parse(fetcher.mock.calls.at(-1)![1].body).organization).toBe("Design team");
  expect(screen.queryByText("Workspace")).toBeNull();
});
