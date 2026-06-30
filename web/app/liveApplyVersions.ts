export type LiveConfigField = "persona" | "mode" | "model";
export type LiveApplyVersions = Record<LiveConfigField, number>;

const LIVE_CONFIG_FIELDS: LiveConfigField[] = ["persona", "mode", "model"];

export function nextLiveApplyVersion(
  versions: LiveApplyVersions,
  field: LiveConfigField,
): { versions: LiveApplyVersions; version: number } {
  const version = versions[field] + 1;
  return { versions: { ...versions, [field]: version }, version };
}

export function invalidateLiveApplyVersions(versions: LiveApplyVersions): LiveApplyVersions {
  return Object.fromEntries(
    LIVE_CONFIG_FIELDS.map((field) => [field, versions[field] + 1]),
  ) as LiveApplyVersions;
}

export function shouldApplyLiveConfig(
  currentEpoch: number,
  ackEpoch: number,
  versions: LiveApplyVersions,
  field: LiveConfigField,
  version: number,
): boolean {
  return currentEpoch === ackEpoch && versions[field] === version;
}
