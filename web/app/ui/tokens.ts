// Single source of truth for the design system (Phase 13 UI overhaul, revamped
// onto the design-mockups/v4 multi-theme system).
//
// The palette values are now CSS-variable REFERENCES rather than hardcoded hex.
// Every config panel imports its shared styles from here, so swapping the active
// theme (via [data-theme] on <html>, see ThemeProvider) re-skins the entire app
// with zero per-component changes. The concrete hex for each theme lives in
// globals.css under the matching [data-theme="…"] block.
//
// Pure constants / typed objects — no React import, no side effects — so it
// tree-shakes cleanly and never pulls weight into the voice-only bundle.

// Theme-driven palette. Each value resolves to the active [data-theme] block in
// globals.css. Key names are unchanged from the pre-theme version so existing
// components need no edits.
export const palette = {
  bg: "var(--bg)", // app background, talking-screen canvas (dominant 60%)
  panel: "var(--panel)", // cards / panels / setup surface (secondary 30%)
  inputBg: "var(--input-bg)", // nested input fields
  border: "var(--line)", // borders
  accent: "var(--accent)", // active segment, agent transcript, focus ring (accent 10%)
  action: "var(--action)", // primary CTA + success only
  warning: "var(--warning)", // transient applying/parsing/distilling/thinking states
  destructive: "var(--destructive)", // errors + leave-session confirmation only
  ink: "var(--ink)", // text/icon color that sits ON an accent/action fill
  text: "var(--text)", // primary text
  textBody: "var(--text-body)", // secondary / body-in-panel text
  textMuted: "var(--text-muted)", // muted / helper text
} as const;

// Spacing scale — multiples of 4 (13-UI-SPEC.md §Spacing Scale).
export const space = {
  xs: "4px",
  sm: "8px",
  md: "16px",
  lg: "24px",
  xl: "32px",
  xxl: "48px",
  xxxl: "64px",
} as const;

// Border radii. Pill/segmented controls use the full-round 999px; the v4 mockups
// use a softer 14px control + 22px card radius.
export const radius = {
  control: "14px",
  card: "22px",
  pill: "999px",
} as const;

// Typography — exactly 4 sizes, 2 weights, line-heights 1.5 body / 1.2 heading.
// No size below 14px.
export const font = {
  size: {
    body: "16px",
    label: "14px",
    heading: "20px",
    display: "28px",
  },
  weight: {
    regular: 400,
    semibold: 600,
  },
  lineHeight: {
    body: 1.5,
    heading: 1.2,
  },
} as const;

// Shared panel container style. Theme-driven via the CSS-variable palette above.
export const panelStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: space.sm,
  width: "20rem",
  padding: space.md,
  border: `1px solid ${palette.border}`,
  borderRadius: radius.card,
  background: palette.panel,
  color: palette.textBody,
  fontSize: font.size.label,
};

// Shared label style (a labeled <label> wrapping its control).
export const labelStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: space.xs,
  fontWeight: font.weight.semibold,
};

// Shared input / select / textarea style.
export const inputStyle: React.CSSProperties = {
  padding: `${space.sm} ${space.sm}`,
  borderRadius: radius.control,
  border: `1px solid ${palette.border}`,
  background: palette.inputBg,
  color: palette.textBody,
  fontWeight: font.weight.regular,
};
