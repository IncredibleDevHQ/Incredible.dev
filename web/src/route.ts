// Where the person is, as an address. Each page has one, each channel's chat and canvas too, and
// on a canvas each task's frame and each card in it, so a link takes anyone straight there:
//   /c/lily                       the channel's chat
//   /c/lily/canvas                its canvas
//   /c/lily/canvas/th_…           a task's frame on it, brought into view
//   /c/lily/canvas/th_…/as_…      a card in that frame (a conversation's opens with its chat)
//   …?thread=th_…                 with that thread open beside it
//   /needs-you, /brand, /brand/<kit>, /brand/new, /skills, /computer
// The address follows the app: a page, a channel, or its chat or canvas is a step Back returns
// from, while what's picked on a canvas and the thread open beside it update the step in place.
// An address opened from a link, and Back and Forward, take the app there.
import type { CanvasTask } from "./api";
import { useHouse, type Focus, type Mode, type State } from "./store";

type Route =
  | { page: "channel"; channel?: string; mode: Mode; task?: string; node?: string; thread?: string }
  | { page: "brand"; kit?: string }
  | { page: "read-brand"; for?: string }
  | { page: "needs" | "skills" | "computer" };

const PAGES = { needs: "/needs-you", skills: "/skills", computer: "/computer" } as const;
const HOUSE_KIT = "default";

const here = () => location.pathname + location.search;
const q = encodeURIComponent;
const part = (text: string) => {
  try {
    return decodeURIComponent(text);
  } catch {
    return text;
  }
};

export function parse(path: string, search: string): Route {
  const [head, ...rest] = path.split("/").filter(Boolean).map(part);
  const query = new URLSearchParams(search);
  if (head === "c" && rest[0]) {
    const [channel, view, task, node] = rest;
    if (view !== "canvas") return { page: "channel", channel, mode: "chat", thread: query.get("thread") ?? undefined };
    return { page: "channel", channel, mode: "canvas", task, node, thread: query.get("thread") ?? undefined };
  }
  if (head === "brand") return rest[0] === "new" ? { page: "read-brand", for: query.get("for") ?? undefined } : { page: "brand", kit: rest[0] };
  const page = (Object.keys(PAGES) as (keyof typeof PAGES)[]).find((p) => PAGES[p] === `/${head}`);
  return page ? { page } : { page: "channel", mode: "chat" };
}

export function addressOf(s: State): string {
  switch (s.page) {
    case "needs":
    case "skills":
    case "computer":
      return PAGES[s.page];
    case "brand":
      return s.brandSlug === HOUSE_KIT ? "/brand" : `/brand/${q(s.brandSlug)}`;
    case "read-brand": {
      const channel = s.channels.find((c) => c.id === s.brandFor);
      return channel ? `/brand/new?for=${q(channel.name)}` : "/brand/new";
    }
    case "channel": {
      const channel = s.channels.find((c) => c.id === s.channelId);
      if (!channel) return "/";
      const canvas = s.mode === "canvas";
      const spot = canvas && s.focus ? `/${q(s.focus.task)}${s.focus.node ? `/${q(s.focus.node)}` : ""}` : "";
      // A conversation's card is picked with its chat open, so its address needs no ?thread.
      const thread = s.threadId && !(canvas && s.focus?.node === s.threadId) ? `?thread=${q(s.threadId)}` : "";
      return `/c/${q(channel.name)}${canvas ? "/canvas" : ""}${spot}${thread}`;
    }
  }
}

// Off until the first address is applied, and while one is.
let following = false;

// Take the app to an address.
export function go(route: Route) {
  const house = useHouse.getState();
  following = false;
  try {
    if (route.page === "brand") house.openBrand(route.kit ?? HOUSE_KIT);
    else if (route.page === "read-brand") house.readBrandFor(house.channels.find((c) => c.name === route.for)?.id ?? null);
    else if (route.page !== "channel") house.openPage(route.page);
    else {
      // A channel goes by its name; an id still finds it, and an unknown one gives the first.
      const channel = house.channels.find((c) => c.name === route.channel || c.id === route.channel) ?? house.channels[0];
      if (!channel) return;
      void house.openChannel(channel.id, route.mode);
      const focus = route.mode === "canvas" && route.task ? { task: route.task, node: route.node ?? null, reveal: true } : null;
      house.focusOn(focus);
      const open = useHouse.getState().threadId;
      if (route.thread) {
        if (route.thread !== open) void house.openThread(route.thread);
      } else if (open && open !== focus?.node) void house.openThread(null);
      if (focus) void land(channel.id, focus, route.thread ?? null);
    }
  } finally {
    following = true;
    const next = addressOf(useHouse.getState());
    if (next !== here()) history.replaceState(null, "", next);
  }
}

// Once the canvas is in, a frame that isn't on it is let go, and a conversation's card opens with
// its chat, as a click on it does.
async function land(channelId: string, focus: Focus, thread: string | null) {
  const tasks = await canvasOf(channelId);
  const s = useHouse.getState();
  if (s.focus?.task !== focus.task || s.focus.node !== focus.node) return;
  const task = tasks.find((t) => t.thread.id === focus.task);
  if (!task) return s.focusOn(null);
  const conversation = task.research?.conversations.some((c) => c.id === focus.node);
  if (conversation && focus.node && !thread && s.threadId !== focus.node) await s.openThread(focus.node);
}

// A channel's canvas, once it has arrived.
function canvasOf(channelId: string) {
  return new Promise<CanvasTask[]>((resolve) => {
    const now = useHouse.getState().canvas[channelId];
    if (now) return resolve(now);
    const stop = useHouse.subscribe((s) => {
      const tasks = s.canvas[channelId];
      if (!tasks) return;
      stop();
      resolve(tasks);
    });
  });
}

// The address bar follows the app from here on; Back and Forward take the app with them.
export function followAddress() {
  const stop = useHouse.subscribe((s, before) => {
    if (!following) return;
    const next = addressOf(s);
    if (next === here()) return;
    const step = s.page !== before.page || s.channelId !== before.channelId || s.mode !== before.mode || s.brandSlug !== before.brandSlug;
    if (step) history.pushState(null, "", next);
    else history.replaceState(null, "", next);
  });
  const travel = () => go(parse(location.pathname, location.search));
  window.addEventListener("popstate", travel);
  return () => {
    stop();
    window.removeEventListener("popstate", travel);
  };
}
