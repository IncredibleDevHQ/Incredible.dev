// Light or dark. A person's pick is kept in this browser; until they pick, or once they pick the
// system's, the system's look is followed. index.html sets the first look before the page
// paints, so it never flashes. Every switch on the page hears a pick made at another (the
// sidebar's, the studio's).
import { useEffect, useState } from "react";

export type Theme = "light" | "dark";
// What a person can pick: one of the looks, or whatever the system has.
export type ThemePick = Theme | "system";

const KEY = "house:theme";
const PICKED = "house:theme-picked";
const system = () => window.matchMedia("(prefers-color-scheme: light)");

function picked(): Theme | null {
  try {
    const value = localStorage.getItem(KEY);
    return value === "light" || value === "dark" ? value : null;
  } catch {
    return null;
  }
}

const current = (): Theme => picked() ?? (system().matches ? "light" : "dark");

export function useTheme(): [Theme, (pick: ThemePick) => void, ThemePick] {
  const [theme, setTheme] = useState<Theme>(current);
  const [chosen, setChosen] = useState<ThemePick>(() => picked() ?? "system");

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  useEffect(() => {
    const media = system();
    const follow = () => {
      if (!picked()) setTheme(current());
    };
    const told = (event: Event) => {
      const { theme: now, chosen: pick } = (event as CustomEvent<{ theme: Theme; chosen: ThemePick }>).detail;
      setTheme(now);
      setChosen(pick);
    };
    media.addEventListener("change", follow);
    window.addEventListener(PICKED, told);
    return () => {
      media.removeEventListener("change", follow);
      window.removeEventListener(PICKED, told);
    };
  }, []);

  const pick = (next: ThemePick) => {
    try {
      if (next === "system") localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, next);
    } catch {
      // Storage is off: the pick holds for this visit only.
    }
    const now: Theme = next === "system" ? (system().matches ? "light" : "dark") : next;
    setTheme(now);
    setChosen(next);
    window.dispatchEvent(new CustomEvent(PICKED, { detail: { theme: now, chosen: next } }));
  };
  return [theme, pick, chosen];
}
