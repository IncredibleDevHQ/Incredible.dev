// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { api } from "../src/api";
import { SettingsPage } from "../src/pages/Settings";
import { parse } from "../src/route";

afterEach(() => { cleanup(); vi.restoreAllMocks(); localStorage.clear(); });

test("usage failure can be retried and unpriced calls have no dollar estimate", async () => {
  const counts = {calls: 1, input_tokens: 120, output_tokens: 20, usd: 0, unpriced: 1};
  const report = {totals: counts, series: [0,1,2].map(at => ({...counts, at})), models: [{...counts, model: "test-model"}]};
  const load = vi.spyOn(api, "usageReport").mockRejectedValueOnce(new Error()).mockResolvedValue(report);
  const user = userEvent.setup();
  render(<SettingsPage tab="usage" />);
  expect(await screen.findByRole("alert")).toBeTruthy();
  await user.click(screen.getByRole("button", { name: "Refresh usage" }));
  expect((await screen.findAllByText("Unavailable")).length).toBe(2);
  expect(screen.getByText("120")).toBeTruthy();
  await user.click(screen.getByRole("button", {name:"Cost", exact:true}));
  expect(screen.getByText("Pricing unavailable for these calls.")).toBeTruthy();
  await user.click(screen.getByRole("button", {name:"Today"}));
  expect(load).toHaveBeenLastCalledWith("today");
  expect(await screen.findByText("test-model")).toBeTruthy();
});

test("start preference affects the home address and preserves deep links", async () => {
  const user = userEvent.setup();
  render(<SettingsPage />);
  const start = screen.getByRole("combobox", {name: /Start page/});
  start.focus();
  await user.keyboard("n");
  expect(parse("/", "").page).toBe("needs");
  expect(parse("/settings", "").page).toBe("settings");
  expect(parse("/c/design", "").page).toBe("channel");
  localStorage.setItem("house:start", "invalid");
  expect(parse("/", "").page).toBe("channel");
});

test("organization edits survive a failed save and can be retried", async () => {
  const profile = {name:"Original", website:"", description:""};
  vi.spyOn(api, "organization").mockResolvedValue(profile);
  const save = vi.spyOn(api, "saveOrganization").mockRejectedValueOnce(new Error()).mockResolvedValue({...profile, name:"Studio"});
  const user = userEvent.setup();
  render(<SettingsPage tab="organization" />);
  const field = await screen.findByLabelText("Organization name");
  await user.clear(field);
  await user.type(field, "Studio");
  await user.click(screen.getByRole("button", {name:"Save changes"}));
  expect(await screen.findByRole("alert")).toBeTruthy();
  await user.click(screen.getByRole("button", {name:"Save changes"}));
  expect(await screen.findByText("Changes saved.")).toBeTruthy();
  expect(save).toHaveBeenLastCalledWith({...profile, name:"Studio"});
  expect(parse("/settings/organization", "").page).toBe("organization");
  expect(parse("/settings/usage", "").page).toBe("usage");
});
