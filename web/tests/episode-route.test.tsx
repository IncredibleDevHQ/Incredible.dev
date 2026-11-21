// @vitest-environment jsdom
import { afterEach, expect, test, vi } from "vitest";
import { addressOf, followAddress, go, parse } from "../src/route";
import { useHouse } from "../src/store";
import { api } from "../src/api";

afterEach(() => {
  vi.restoreAllMocks();
  useHouse.setState(useHouse.getInitialState());
  history.replaceState(null, "", "/");
});

test("a chapter recording link survives route application and can return to the film", () => {
  vi.spyOn(api, "channelMessages").mockResolvedValue({ roots: [], threads: {}, replies: {} });
  vi.spyOn(api, "episode").mockImplementation(() => new Promise(() => {}));
  vi.spyOn(api, "canvas").mockImplementation(() => new Promise(() => {}));
  useHouse.setState({ channels: [{ id: "channel", name: "Studio", topic: "", created_at: 0 }] });
  const stop = followAddress();
  try {
    const url = "/c/Studio/episode/ep_test";
    history.replaceState(null, "", url + "?at=c2&line=c2.b1.f1&record=1");
    go(parse(location.pathname, location.search));
    expect(addressOf(useHouse.getState())).toBe(url + "?at=c2&line=c2.b1.f1&record=1");
    go(parse(url, "?at=c2&line=c2.b1.f2"));
    expect(addressOf(useHouse.getState())).toBe(url + "?at=c2&line=c2.b1.f2");
    go(parse(url, ""));
    expect(addressOf(useHouse.getState())).toBe(url);
  } finally {
    stop();
  }
});
