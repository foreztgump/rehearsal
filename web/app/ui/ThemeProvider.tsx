"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

import {
  DEFAULT_THEME_ID,
  THEME_STORAGE_KEY,
  getTheme,
  isThemeId,
  type Theme,
  type ThemeId,
} from "./themes";

type ThemeContextValue = {
  themeId: ThemeId;
  theme: Theme;
  setThemeId: (id: ThemeId) => void;
};

const ThemeContext = createContext<ThemeContextValue | null>(null);

/**
 * Runtime theme provider for the six design-mockups/v4 palettes. Writes the
 * active id to `<html data-theme="…">` (the selector the globals.css palette
 * blocks key off of) and persists the choice in localStorage so it survives a
 * reload. SSR renders the default theme; the stored choice is hydrated in an
 * effect (no flash beyond the first paint, and the default block matches the
 * server-rendered `data-theme`).
 */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const [themeId, setThemeIdState] = useState<ThemeId>(DEFAULT_THEME_ID);

  // Hydrate the persisted choice once on mount.
  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
      if (isThemeId(stored)) setThemeIdState(stored);
    } catch {
      // localStorage blocked (private mode / disabled) — keep the default.
    }
  }, []);

  // Reflect the active theme onto <html> and persist it.
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", themeId);
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, themeId);
    } catch {
      // Non-fatal: the theme still applies for this session.
    }
  }, [themeId]);

  const value: ThemeContextValue = {
    themeId,
    theme: getTheme(themeId),
    setThemeId: setThemeIdState,
  };

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) {
    throw new Error("useTheme must be used within a ThemeProvider");
  }
  return ctx;
}
