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
