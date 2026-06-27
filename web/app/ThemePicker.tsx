"use client";

import { THEMES } from "./ui/themes";
import { useTheme } from "./ui/ThemeProvider";
import { font, palette, panelStyle, radius, space } from "./ui/tokens";

/**
 * Theme selector for the landing/setup screen. Renders the six design-mockups/v4
 * palettes as a grid of selectable swatch tiles; choosing one updates the live
 * theme (ThemeProvider persists it to localStorage). Presentational beyond the
 * single useTheme() binding — no LiveKit dependency, safe outside <LiveKitRoom>.
 */
export default function ThemePicker() {
  const { themeId, setThemeId } = useTheme();

  return (
    <div style={panelStyle}>
      <strong style={{ fontSize: font.size.heading }}>Theme</strong>
      <span style={{ color: palette.textMuted }}>Pick a look for your session.</span>
      <div
        role="radiogroup"
        aria-label="Theme"
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
          gap: space.sm,
          marginTop: space.xs,
        }}
      >
        {THEMES.map((theme) => {
          const active = theme.id === themeId;
          return (
            <button
              key={theme.id}
              type="button"
              role="radio"
              aria-checked={active}
              className="transition-hover"
              onClick={() => setThemeId(theme.id)}
              style={{
                display: "flex",
                alignItems: "center",
                gap: space.sm,
                padding: space.sm,
                borderRadius: radius.control,
                border: `1px solid ${active ? palette.accent : palette.border}`,
                background: active ? palette.inputBg : "transparent",
                color: palette.text,
                cursor: "pointer",
                textAlign: "left",
                boxShadow: active ? `0 0 0 1px ${palette.accent}` : "none",
              }}
            >
              {/* Swatch: theme bg field with an accent dot. */}
              <span
                aria-hidden="true"
                style={{
                  flex: "0 0 auto",
                  width: "28px",
                  height: "28px",
                  borderRadius: "8px",
                  background: theme.swatch.bg,
                  border: `1px solid ${palette.border}`,
                  display: "grid",
                  placeItems: "center",
                }}
              >
                <span
                  style={{
                    width: "14px",
                    height: "14px",
                    borderRadius: "999px",
                    background: theme.swatch.accent,
                  }}
                />
              </span>
              <span style={{ display: "flex", flexDirection: "column", gap: "2px", minWidth: 0 }}>
                <span style={{ fontWeight: font.weight.semibold, fontSize: font.size.label }}>
                  {theme.name}
                </span>
                <span
                  style={{
                    color: palette.textMuted,
                    fontSize: "12px",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {theme.blurb}
                </span>
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
