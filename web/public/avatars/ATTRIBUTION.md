# Avatar attribution & licensing

The 3D avatar faces in this folder are TalkingHead-compatible GLBs (Mixamo rig +
ARKit-52 blendshapes + Oculus-15 visemes). Compatibility is checked by
`scripts/verify-avatars.mjs`.

> **Note on sourcing:** Ready Player Me shut down its public avatar platform on
> **2026-01-31** (Netflix acquisition), so new avatars can no longer be generated
> through its API. The faces below are pre-made and vendored into the repo. To add
> more, use a TalkingHead-compatible source (e.g. Avatar SDK / MetaPerson) and run
> the verify script. Note: `scripts/verify-avatars.mjs` rejects meshopt-compressed
> GLBs (`EXT_meshopt_compression`) — AvatarStage wires only the Draco decoder, so a
> meshopt file fails to load. Re-export as uncompressed or Draco.

| File | Source | License |
| --- | --- | --- |
| `cyber-trainer.glb` | Ready Player Me (created before shutdown) | CC BY-NC 4.0 (non-commercial) |
| `brunette.glb` | Ready Player Me, via [met4citizen/TalkingHead](https://github.com/met4citizen/TalkingHead) example set | CC BY-NC 4.0 (non-commercial) |
| `avaturn.glb` | [Avaturn](https://avaturn.me), via TalkingHead example set | Free for non-commercial use |
| `avatarsdk.glb` | [Avatar SDK / MetaPerson](https://avatarsdk.com), via TalkingHead example set | Per Avatar SDK terms (non-commercial sample) |

All faces here are used under **non-commercial** terms, consistent with Adept's
local-first, personal-use design. If you need commercially-licensed avatars, replace
these with your own TalkingHead-compatible GLBs and update `AVATAR_CATALOG` in
`web/app/avatarConfig.ts`.
