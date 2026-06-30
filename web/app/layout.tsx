import type { ReactNode } from "react";

import { ThemeProvider } from "./ui/ThemeProvider";
import { DEFAULT_THEME_ID } from "./ui/themes";

import "./globals.css";

export const metadata = {
  title: "Rehearsal",
  description: "Private voice practice with expert personas.",
};

// Same-origin importmap for the OPTIONAL 3D avatar (Phase 12). Maps the bare
// specifiers TalkingHead imports (`three`, `three/addons/`, `talkinghead`) to the
// vendored copies under /vendor (no CDN/WAN runtime dependency). It must be emitted
// in <head> BEFORE any module that resolves those specifiers — AvatarStage is only
// dynamic-imported on Avatar-toggle-ON, so this ordering holds. Inert for voice-only:
// nothing imports these specifiers until the avatar mounts.
const AVATAR_IMPORTMAP = JSON.stringify({
  imports: {
    three: "/vendor/three/three.module.js",
    "three/addons/": "/vendor/three/addons/",
    talkinghead: "/vendor/talkinghead/talkinghead.mjs",
  },
});

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    // data-theme seeds the default palette block for SSR; ThemeProvider rewrites
    // it on the client once the persisted choice is hydrated.
    <html lang="en" data-theme={DEFAULT_THEME_ID}>
      <head>
        <script
          type="importmap"
          dangerouslySetInnerHTML={{ __html: AVATAR_IMPORTMAP }}
        />
      </head>
      <body
        style={{
          fontFamily: "system-ui, sans-serif",
          margin: 0,
          minHeight: "100vh",
        }}
      >
        <ThemeProvider>
          {/* Ambient drifting wash + film grain backdrop (theme-driven, CSS-only,
              pointer-events:none — sits behind app content at z-index 0/1). */}
          <div className="ambient" aria-hidden="true" />
          <div className="grain" aria-hidden="true" />
          <div style={{ position: "relative", zIndex: 2, minHeight: "100vh" }}>
            {children}
          </div>
        </ThemeProvider>
      </body>
    </html>
  );
}
