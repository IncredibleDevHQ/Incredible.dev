// Light or dark. A person's pick is kept in this browser; until they pick, the system's look is
// followed. index.html sets the first look before the page paints, so it never flashes. Every
// switch on the page hears a pick made at another (the sidebar's, the studio's).
import { useEffect, useState } from "react";

export type Theme = "light" | "dark";

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

export function useTheme(): [Theme, (theme: Theme) => void] {
  const [theme, setTheme] = useState<Theme>(current);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  useEffect(() => {
    const media = system();
    const follow = () => {
      if (!picked()) setTheme(current());
    };
    const told = (event: Event) => setTheme((event as CustomEvent<Theme>).detail);
    media.addEventListener("change", follow);
    window.addEventListener(PICKED, told);
    return () => {
      media.removeEventListener("change", follow);
      window.removeEventListener(PICKED, told);
    };
  }, []);

  const pick = (next: Theme) => {
    try {
      localStorage.setItem(KEY, next);
    } catch {
      // Storage is off: the pick holds for this visit only.
    }
    setTheme(next);
    window.dispatchEvent(new CustomEvent<Theme>(PICKED, { detail: next }));
  };
  return [theme, pick];
}
