import type { ReactNode } from "react";

export const metadata = {
  title: "Adept",
  description: "Near-real-time voice persona trainer",
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
    <html lang="en">
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
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "#0b0f14",
          color: "#e6edf3",
        }}
      >
        {children}
      </body>
    </html>
  );
}
