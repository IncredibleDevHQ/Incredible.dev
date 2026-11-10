// Light or dark. A person's pick is kept in this browser; until they pick, the system's look is
// followed. index.html sets the first look before the page paints, so it never flashes.
import { useEffect, useState } from "react";

export type Theme = "light" | "dark";

const KEY = "house:theme";
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
    media.addEventListener("change", follow);
    return () => media.removeEventListener("change", follow);
  }, []);

  const pick = (next: Theme) => {
    try {
      localStorage.setItem(KEY, next);
    } catch {
      // Storage is off: the pick holds for this visit only.
    }
    setTheme(next);
  };
  return [theme, pick];
}
