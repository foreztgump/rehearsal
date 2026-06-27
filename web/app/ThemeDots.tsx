"use client";

import { THEMES } from "./ui/themes";
import { useTheme } from "./ui/ThemeProvider";

/**
 * Compact always-visible theme switcher — a row of six swatch dots (one per
 * design-mockups/v4 palette). Each dot shows the theme's accent over its bg; the
 * active theme gets an accent ring. Chosen so the switcher blends into whatever
 * theme is live (the ring + hover both key off `var(--accent)`), unlike the
 * verbose ThemePicker card. Presentational beyond the single useTheme() binding —
 * no LiveKit dependency, safe inside or outside <LiveKitRoom>.
 *
 * Surfaced in the setup-screen header and the in-room Settings drawer so the look
 * is switchable both before and during a session.
 */
export default function ThemeDots() {
  const { themeId, setThemeId } = useTheme();

  return (
    <div className="theme-dots" role="radiogroup" aria-label="Theme">
      {THEMES.map((theme) => {
        const active = theme.id === themeId;
        return (
          <button
            key={theme.id}
            type="button"
            role="radio"
            aria-checked={active}
            aria-label={theme.name}
            title={theme.name}
            className={active ? "theme-dot on" : "theme-dot"}
            onClick={() => setThemeId(theme.id)}
            style={{ background: theme.swatch.bg }}
          >
            <span aria-hidden="true" style={{ background: theme.swatch.accent }} />
          </button>
        );
      })}
    </div>
  );
}
