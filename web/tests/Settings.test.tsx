// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { api } from "../src/api";
import { SettingsPage } from "../src/pages/Settings";
import { parse } from "../src/route";

afterEach(() => { cleanup(); vi.restoreAllMocks(); localStorage.clear(); });

test("usage failure can be retried and unpriced calls have no dollar estimate", async () => {
  vi.spyOn(api, "usage").mockRejectedValueOnce(new Error()).mockResolvedValue({
    calls: 1, input_tokens: 120, output_tokens: 20, usd: 0, unpriced: 1,
  });
  const user = userEvent.setup();
  render(<SettingsPage />);
  expect(await screen.findByRole("alert")).toBeTruthy();
  await user.click(screen.getByRole("button", { name: "Refresh usage" }));
  expect(await screen.findByText("Unavailable")).toBeTruthy();
  expect(screen.getByText("120")).toBeTruthy();
});

test("start preference affects the home address and preserves deep links", async () => {
  vi.spyOn(api, "usage").mockResolvedValue({calls: 0, input_tokens: 0, output_tokens: 0, usd: 0, unpriced: 0});
  const user = userEvent.setup();
  render(<SettingsPage />);
  expect(await screen.findByText("No model calls recorded yet.")).toBeTruthy();
  const start = screen.getByRole("combobox", {name: /Start page/});
  start.focus();
  await user.keyboard("n");
  expect(parse("/", "").page).toBe("needs");
  expect(parse("/settings", "").page).toBe("settings");
  expect(parse("/c/design", "").page).toBe("channel");
  localStorage.setItem("house:start", "invalid");
  expect(parse("/", "").page).toBe("channel");
});
