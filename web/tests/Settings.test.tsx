// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, afterEach, expect, test, vi } from "vitest";
import { api } from "../src/api";
import { SettingsPage } from "../src/pages/Settings";
import { useHouse } from "../src/store";
import { parse } from "../src/route";

beforeEach(()=>{vi.spyOn(api,"organization").mockResolvedValue({name:"Studio",website:"",description:""});vi.spyOn(api,"team").mockResolvedValue({owner:"owner@example.com",project:"owner",personal_url:"/",can_manage:true,incoming:[],members:[]});vi.stubGlobal("matchMedia",()=>({matches:false,addEventListener(){},removeEventListener(){}}));vi.spyOn(api,"accountDetails").mockResolvedValue({});});

afterEach(() => { cleanup(); vi.unstubAllGlobals(); useHouse.setState(useHouse.getInitialState()); vi.restoreAllMocks(); localStorage.clear(); });

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
  expect(screen.queryByText("View chart data")).toBeNull();
  await user.click(screen.getByRole("button", {name:"Line chart"}));
  expect(screen.getByRole("button", {name:"Line chart"}).getAttribute("aria-pressed")).toBe("true");
  await user.click(screen.getByRole("button", {name:"Cost", exact:true}));
  expect(screen.getByText("Pricing unavailable for these calls.")).toBeTruthy();
  await user.click(screen.getByRole("button", {name:"Today"}));
  expect(load).toHaveBeenLastCalledWith("today");
  expect(await screen.findByText("test-model")).toBeTruthy();
  expect(screen.getByRole("button", {name:"Line chart"}).getAttribute("aria-pressed")).toBe("true");
  expect(screen.getByRole("img", {name:/Cost by hour/})).toBeTruthy();
});

test("start preference affects the home address and preserves deep links", async () => {
  const user = userEvent.setup();
  render(<SettingsPage tab="preferences" />);
  const start = screen.getByRole("combobox", {name: /Start page/});
  start.focus();
  await user.keyboard("n");
  expect(parse("/", "").page).toBe("needs");
  expect(parse("/settings/members", "").page).toBe("organization");
  expect(parse("/settings", "").page).toBe("profile");
  expect(parse("/settings/preferences", "").page).toBe("preferences");
  expect(parse("/c/design", "").page).toBe("channel");
  localStorage.setItem("house:start", "invalid");
  expect(parse("/", "").page).toBe("channel");
});

test("settings opens device preferences when there is no signed-in profile", () => {
  useHouse.getState().openPage("profile");
  expect(useHouse.getState().page).toBe("preferences");
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
  await user.clear(screen.getByLabelText("Display name"));
  await user.type(screen.getByLabelText("Display name"),"After");
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
  render(<SettingsPage tab="preferences" />);
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
  expect(Array.from(screen.getByRole("navigation",{name:"Settings sections"}).querySelectorAll("a")).map(link => link.textContent)).toEqual(["Profile","Organization","Preferences","Usage","Logs"]);
  expect(screen.getByText("Read only")).toBeTruthy();
  expect(screen.getByLabelText("Primary email").hasAttribute("readonly")).toBe(true);
  expect((await screen.findByLabelText("First name")).getAttribute("placeholder")).toBeTruthy();
  expect(screen.queryByLabelText("Avatar color")).toBeNull();
  const image = new File(["picture"],"photo.png",{type:"image/png"});
  await user.upload(screen.getByLabelText("Avatar image"),image);
  expect(await screen.findByText("Avatar saved.")).toBeTruthy();
  expect(upload).toHaveBeenCalledWith(image);
  expect(useHouse.getState().people.me.avatar_file).toBe("file_photo");
  expect(screen.getByRole("button",{name:"Change avatar"})).toBeTruthy();
});

test("account details keep the draft when a username is taken", async () => {
  useHouse.setState({session:{me:"account",people:[],authenticated:true,demo:false,agent:{mark:"house",model:"test"},sandbox:null}});
  vi.spyOn(api,"passwordState").mockResolvedValue({user:{has_password:true}});
  const save=vi.spyOn(api,"saveAccountDetails").mockRejectedValueOnce(new Error("That username is already in use."))
    .mockResolvedValue({first_name:"Alex",username:"alex_studio"});
  render(<SettingsPage tab="profile"/>);
  const user=userEvent.setup();
  await user.type(await screen.findByLabelText("First name"),"Alex");
  const username=screen.getByLabelText("Username");
  await user.type(username,"taken_name");
  await user.click(screen.getByRole("button",{name:"Save account details"}));
  expect(await screen.findByText("That username is already in use.")).toBeTruthy();
  await user.clear(username);
  await user.type(username,"alex_studio");
  await user.click(screen.getByRole("button",{name:"Save account details"}));
  expect(await screen.findByText("Account details saved.")).toBeTruthy();
  expect(save).toHaveBeenLastCalledWith({first_name:"Alex",username:"alex_studio"});
});

test("member removal needs confirmation and refreshes the roster", async () => {
  useHouse.setState({session:{me:"owner",people:[],authenticated:true,demo:false,agent:{mark:"house",model:"test"},sandbox:null}});
  const team={project:"owner", personal_url:"/",owner:"owner@example.com",can_manage:true,incoming:[],members:[]};
  vi.spyOn(api,"team").mockResolvedValueOnce({...team,members:[{id:"invite",email:"member@example.com",member:"member"}]}).mockResolvedValue(team);
  const remove=vi.spyOn(api,"removeMember").mockResolvedValue({});
  const user=userEvent.setup();
  render(<SettingsPage tab="organization"/>);
  await user.click(await screen.findByRole("button",{name:"Actions for member@example.com"}));
  await user.click(await screen.findByRole("menuitem",{name:"Remove access"}));
  expect(remove).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button",{name:"Confirm removal"}));
  expect(remove).toHaveBeenCalledWith("invite");
  expect(screen.queryByText("member@example.com")).toBeNull();
});

test("members invites from a named dialog and shows a pending table row", async () => {
  useHouse.setState({session:{me:"owner",people:[],authenticated:true,demo:false,agent:{mark:"house",model:"test"},sandbox:null}});
  const roster={project:"owner",personal_url:"/",owner:"owner@example.com",can_manage:true,incoming:[],members:[]};
  vi.spyOn(api,"team").mockResolvedValueOnce(roster).mockResolvedValue({...roster,members:[{id:"new",email:"new@example.com",member:null}]});
  vi.spyOn(api,"invite").mockResolvedValue({id:"new",invite_url:"https://project.example/invite/new",email_sent:true});
  const user=userEvent.setup();
  render(<SettingsPage tab="organization"/>);
  await user.click(await screen.findByRole("button",{name:"Invite member"}));
  expect(screen.getByRole("dialog",{name:"Invite member"})).toBeTruthy();
  await user.type(screen.getByLabelText("Invite by email"),"new@example.com");
  await user.click(screen.getByRole("button",{name:"Send invitation"}));
  expect(await screen.findByRole("row",{name:/new@example.com.*Pending/i})).toBeTruthy();
  expect(screen.queryByRole("dialog")).toBeNull();
  await user.click(screen.getByRole("button",{name:"Actions for new@example.com"}));
  await user.click(await screen.findByRole("menuitem",{name:"Copy invite link"}));
  expect(await navigator.clipboard.readText()).toBe("https://project.example/invite/new");
});

test("organization exposes the invitation role before submission", async () => {
  useHouse.setState({session:{me:"owner",people:[],authenticated:true,demo:false,agent:{mark:"house",model:"test"},sandbox:null}});
  vi.spyOn(api,"organization").mockResolvedValue({name:"Studio",website:"",description:""});
  vi.spyOn(api,"team").mockResolvedValue({owner:"owner@example.com",project:"owner",personal_url:"/",can_manage:true,incoming:[],members:[]});
  render(<SettingsPage tab="organization"/>);
  await userEvent.click(await screen.findByRole("button",{name:"Invite member"}));
  expect(screen.getByRole("dialog").textContent).toContain("Manage channels");
  expect(screen.getByLabelText("Invite by email").getAttribute("data-slot")).toBe("input");
});

test("a log entry opens its details and closes with Escape", async () => {
  useHouse.setState({session:{me:"owner",people:[],authenticated:true,demo:false,agent:{mark:"house",model:"test"},sandbox:null}});
  vi.spyOn(api,"activity").mockResolvedValue({events:[{id:"event-1",actor:"owner",actor_email:"owner@example.com",action:"PUT /api/profile",status:200,happened:12}],actors:[],more:false});
  render(<SettingsPage tab="logs"/>);
  const filter = await screen.findByRole("combobox", {name:/Performed by/});
  const toolbar = screen.getByRole("group", {name:"Activity controls"});
  expect(toolbar.contains(filter)).toBe(true);
  expect(filter.compareDocumentPosition(screen.getByRole("button",{name:"Refresh activity"})) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  await userEvent.click(await screen.findByText("Updated display name"));
  const dialog=screen.getByRole("dialog",{name:"Event details"});
  expect(dialog.textContent).toContain("event-1");
  expect(dialog.textContent).toContain("PUT /api/profile");
  await userEvent.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).toBeNull();
  await waitFor(()=>expect(document.activeElement).toBe(screen.getByRole("button",{name:"Updated display name"})));
});
