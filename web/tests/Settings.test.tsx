// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { api } from "../src/api";
import { SettingsPage } from "../src/pages/Settings";
import { useHouse } from "../src/store";
import { parse } from "../src/route";

afterEach(() => { cleanup(); useHouse.setState(useHouse.getInitialState()); vi.restoreAllMocks(); localStorage.clear(); });

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
  useHouse.setState({session: {me:"user", people:[], authenticated:true, organizationName:"Original",
    demo:false, agent:{mark:"house", model:"test"}, sandbox:null}});
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
  expect(useHouse.getState().session?.organizationName).toBe("Original");
  await user.click(screen.getByRole("button", {name:"Save changes"}));
  expect(await screen.findByText("Changes saved.")).toBeTruthy();
  expect(useHouse.getState().session?.organizationName).toBe("Studio");
  expect(save).toHaveBeenLastCalledWith({...profile, name:"Studio"});
  expect(parse("/settings/organization", "").page).toBe("organization");
  expect(parse("/settings/usage", "").page).toBe("usage");
});

test("the usage skeleton is accessible until the report resolves", () => {
  vi.spyOn(api, "usageReport").mockReturnValue(new Promise(() => {}));
  render(<SettingsPage tab="usage" />);
  expect(screen.getByRole("status", {name: "Loading usage"})).toBeTruthy();
  expect(screen.queryByText("Checking usage…")).toBeNull();
});

test.each([false, true])("password settings handle existing password %s", async has_password => {
  useHouse.setState({session: {me:"user", people:[], authenticated:true, demo:false, agent:{mark:"house",model:"test"},sandbox:null}});
  vi.spyOn(api,"passwordState").mockResolvedValue({user:{has_password}});
  const save = vi.spyOn(api,"savePassword").mockRejectedValueOnce(new Error("Try again")).mockResolvedValue({has_password:true});
  const user=userEvent.setup();
  render(<SettingsPage tab="profile" />);
  if (has_password) {
    const verify = vi.spyOn(api,"verifyPassword").mockRejectedValueOnce(new Error("Incorrect password")).mockResolvedValue({verified:true});
    await user.type(await screen.findByLabelText("Current password"), "previous-pass");
    const confirm = screen.getByRole("button",{name:"Confirm current password"});
    await user.click(confirm);
    expect(await screen.findByText("Incorrect password")).toBeTruthy();
    expect(screen.queryByLabelText("New password")).toBeNull();
    await user.click(confirm);
    expect(verify).toHaveBeenCalledWith("previous-pass");
  }
  const field = await screen.findByLabelText("New password");
  await user.type(field, "new-test-password");
  const submit=screen.getByRole("button",{name:has_password ? "Update password" : "Set password"});
  await user.click(submit);
  expect(await screen.findByRole("alert")).toBeTruthy();
  await user.click(submit);
  expect(await screen.findByText(has_password ? "Password updated." : "Password set.")).toBeTruthy();
  expect(screen.getByRole("heading",{name:"Update password"})).toBeTruthy();
  expect(screen.queryByLabelText("New password")).toBeNull();
  expect(save).toHaveBeenCalledWith("new-test-password", has_password ? "previous-pass" : undefined);
});

test("saving the profile updates the visible username and color", async () => {
  const person = {id:"me",name:"Before",hue:152,initials:"B",agent:false};
  useHouse.setState({people:{me:person},session:{me:"me",people:[person],authenticated:true,email:"me@example.com",demo:false,agent:{mark:"house",model:"test"},sandbox:null}});
  vi.spyOn(api,"passwordState").mockResolvedValue({user:{has_password:false}});
  vi.spyOn(api,"saveProfile").mockResolvedValue({...person,name:"After",initials:"A"});
  const user=userEvent.setup();
  render(<SettingsPage tab="profile" />);
  await user.clear(screen.getByLabelText("Username"));
  await user.type(screen.getByLabelText("Username"),"After");
  await user.click(screen.getByRole("button",{name:"Save profile"}));
  expect(await screen.findByText("Profile saved.")).toBeTruthy();
  expect(useHouse.getState().people.me.name).toBe("After");
  expect(parse("/settings/profile","").page).toBe("profile");
});

test("chat defaults save the provider's selected model and reset incompatible effort", async () => {
  const models = [
    {id:"openai:first", provider:"openai", name:"First", efforts:["high"]},
    {id:"anthropic:second", provider:"anthropic", name:"Second", efforts:["low"]},
  ];
  useHouse.setState({session:{me:"me",people:[],authenticated:true,demo:false,agent:{mark:"house",model:"test"},sandbox:null}});
  vi.spyOn(api,"modelDefaults").mockResolvedValue({options:models, default:"openai:first",model:"openai:first",effort:"high"});
  const save=vi.spyOn(api,"saveModelDefaults").mockResolvedValue({model:"anthropic:second",effort:"low"});
  const user=userEvent.setup();
  render(<SettingsPage />);
  (await screen.findByRole("combobox",{name:/Default provider/})).focus();
  await user.keyboard("c");
  const effort=screen.getByRole("slider",{name:"Effort"});
  expect((effort as HTMLInputElement).value).toBe("0");
  effort.focus();
  fireEvent.change(effort,{target:{value:"1"}});
  await user.click(screen.getByRole("button",{name:"Save defaults"}));
  expect(await screen.findByText("Defaults saved.")).toBeTruthy();
  expect(save).toHaveBeenCalledWith("anthropic:second","low");
});

test("profile uploads an avatar and keeps the requested navigation order", async () => {
  const person = {id:"me",name:"Alex",hue:152,initials:"A",agent:false};
  useHouse.setState({people:{me:person},session:{me:"me",people:[person],authenticated:true,demo:false,agent:{mark:"house",model:"test"},sandbox:null}});
  vi.spyOn(api,"passwordState").mockResolvedValue({user:{has_password:false}});
  const upload = vi.spyOn(api,"uploadAvatar").mockResolvedValue({...person,avatar_file:"file_photo"});
  const user = userEvent.setup();
  render(<SettingsPage tab="profile" />);
  expect(screen.getAllByRole("link").map(link => link.textContent)).toEqual(["Profile","Organization","Preferences","Usage"]);
  expect(screen.queryByLabelText("Avatar color")).toBeNull();
  const image = new File(["picture"],"photo.png",{type:"image/png"});
  await user.upload(screen.getByLabelText("Avatar image"),image);
  expect(await screen.findByText("Avatar saved.")).toBeTruthy();
  expect(upload).toHaveBeenCalledWith(image);
  expect(useHouse.getState().people.me.avatar_file).toBe("file_photo");
  expect(screen.getByRole("button",{name:"Change avatar"})).toBeTruthy();
});
