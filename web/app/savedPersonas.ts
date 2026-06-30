export const SAVED_PERSONAS_KEY = "adept.savedPersonas.v1";

export const PERSONA_VOICE_IDS = [
  "af_heart",
  "af_bella",
  "af_nicole",
  "af_sarah",
  "af_kore",
  "am_michael",
  "am_fenrir",
  "am_puck",
  "am_adam",
  "bf_emma",
  "bf_alice",
  "bm_george",
  "bm_daniel",
] as const;

export const PERSONA_DIFFICULTY = ["beginner", "intermediate", "expert"] as const;
export const PERSONA_VERBOSITY = ["terse", "balanced", "detailed"] as const;
export const PERSONA_CORRECTION = ["gentle", "moderate", "aggressive"] as const;

export type Persona = {
  role_text: string;
  display_name: string;
  difficulty: string;
  verbosity: string;
  correction: string;
  voice_id: string;
};

export type SavedPersona = {
  id: string;
  name: string;
  persona: Persona;
  createdAt: string;
  updatedAt: string;
};

export type SavedPersonaMutationResult = { ok: boolean; personas: SavedPersona[] };

type StorageLike = {
  getItem: (key: string) => string | null;
  setItem: (key: string, value: string) => void;
  removeItem: (key: string) => void;
};

const PERSONA_FIELDS = [
  "role_text",
  "display_name",
  "difficulty",
  "verbosity",
  "correction",
  "voice_id",
] as const;

export function parseSavedPersonas(raw: string | null): SavedPersona[] {
  if (!raw) return [];

  try {
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter(isSavedPersona) : [];
  } catch {
    return [];
  }
}

export function readSavedPersonas(storage?: StorageLike | null): SavedPersona[] {
  const target = resolveStorage(storage);
  if (!target) return [];

  return readSavedPersonasForMutation(target) ?? [];
}

function readSavedPersonasForMutation(storage: StorageLike): SavedPersona[] | null {
  try {
    return parseSavedPersonas(storage.getItem(SAVED_PERSONAS_KEY));
  } catch {
    return null;
  }
}

export function saveSavedPersona(
  persona: Persona,
  name: string,
  storage?: StorageLike | null,
): SavedPersona[] {
  return saveSavedPersonaResult(persona, name, storage).personas;
}

export function saveSavedPersonaResult(
  persona: Persona,
  name: string,
  storage?: StorageLike | null,
): SavedPersonaMutationResult {
  const target = resolveStorage(storage);
  if (!target) return { ok: false, personas: [] };

  const current = readSavedPersonasForMutation(target);
  if (!current) return { ok: false, personas: [] };

  const trimmedName = name.trim();
  if (!trimmedName || !isPersona(persona)) return { ok: false, personas: current };

  const now = new Date().toISOString();
  const match = current.findIndex((item) => sameName(item.name, trimmedName));
  const next = [...current];
  if (match >= 0) {
    next[match] = { ...current[match], name: trimmedName, persona, updatedAt: now };
  } else {
    next.push({ id: newId(), name: trimmedName, persona, createdAt: now, updatedAt: now });
  }

  return writeSavedPersonas(target, next)
    ? { ok: true, personas: next }
    : { ok: false, personas: current };
}

export function deleteSavedPersona(id: string, storage?: StorageLike | null): SavedPersona[] {
  return deleteSavedPersonaResult(id, storage).personas;
}

export function deleteSavedPersonaResult(
  id: string,
  storage?: StorageLike | null,
): SavedPersonaMutationResult {
  const target = resolveStorage(storage);
  if (!target) return { ok: false, personas: [] };

  const current = readSavedPersonasForMutation(target);
  if (!current) return { ok: false, personas: [] };

  const next = current.filter((item) => item.id !== id);
  if (next.length === current.length) return { ok: false, personas: current };

  return writeSavedPersonas(target, next)
    ? { ok: true, personas: next }
    : { ok: false, personas: current };
}

function isSavedPersona(value: unknown): value is SavedPersona {
  if (!isRecord(value)) return false;

  return (
    hasText(value.id) &&
    hasText(value.name) &&
    hasText(value.createdAt) &&
    hasText(value.updatedAt) &&
    isPersona(value.persona)
  );
}

function isPersona(value: unknown): value is Persona {
  if (!isRecord(value)) return false;

  return (
    PERSONA_FIELDS.every((field) => typeof value[field] === "string") &&
    hasValue(PERSONA_DIFFICULTY, value.difficulty) &&
    hasValue(PERSONA_VERBOSITY, value.verbosity) &&
    hasValue(PERSONA_CORRECTION, value.correction) &&
    hasValue(PERSONA_VOICE_IDS, value.voice_id)
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function hasText(value: unknown): value is string {
  return typeof value === "string" && value.trim() !== "";
}

function hasValue(values: readonly string[], value: unknown): value is string {
  return typeof value === "string" && values.includes(value);
}

function resolveStorage(storage?: StorageLike | null): StorageLike | null {
  if (storage !== undefined) return storage;
  if (typeof window === "undefined") return null;

  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function writeSavedPersonas(storage: StorageLike, personas: SavedPersona[]): boolean {
  try {
    if (personas.length === 0) {
      storage.removeItem(SAVED_PERSONAS_KEY);
    } else {
      storage.setItem(SAVED_PERSONAS_KEY, JSON.stringify(personas));
    }
    return true;
  } catch {
    return false;
  }
}

function sameName(left: string, right: string): boolean {
  return left.trim().toLowerCase() === right.trim().toLowerCase();
}

function newId(): string {
  try {
    if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
  } catch {
    // Fall back below.
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

function memoryStorage(): StorageLike {
  let value: string | null = null;
  return {
    getItem: () => value,
    setItem: (_key, next) => { value = next; },
    removeItem: () => { value = null; },
  };
}

export function selfCheck() {
  const persona: Persona = {
    role_text: "You are a test coach.",
    display_name: "Test Coach",
    difficulty: "intermediate",
    verbosity: "balanced",
    correction: "gentle",
    voice_id: "af_bella",
  };
  const valid: SavedPersona = {
    id: "one",
    name: "Test",
    persona,
    createdAt: "2026-06-30T00:00:00.000Z",
    updatedAt: "2026-06-30T00:00:00.000Z",
  };

  const parsed = parseSavedPersonas(JSON.stringify([valid, { name: "", persona }]));
  assert(parsed.length === 1, "valid record was not parsed");
  assert(parsed[0].name === "Test", "saved persona name changed");

  const storage = memoryStorage();
  let saved = saveSavedPersona(persona, "My Coach", storage);
  assert(saved.length === 1, "save did not create one record");
  saved = saveSavedPersona({ ...persona, display_name: "Updated Coach" }, "My Coach", storage);
  assert(saved.length === 1, "same-name save created a duplicate");
  assert(saved[0].persona.display_name === "Updated Coach", "same-name save did not update");
  saved = deleteSavedPersona(saved[0].id, storage);
  assert(saved.length === 0, "delete did not remove record");

  let writes = 0;
  const failingReadStorage: StorageLike = {
    getItem: () => {
      throw new Error("read failed");
    },
    setItem: () => {
      writes += 1;
    },
    removeItem: () => {
      writes += 1;
    },
  };
  saveSavedPersona(persona, "Unsafe Write", failingReadStorage);
  assert(writes === 0, "save wrote after storage read failed");
  const saveResult = saveSavedPersonaResult(persona, "Unsafe Write", failingReadStorage);
  assert(saveResult.ok === false, "save reported success after storage read failed");
  assert(writes === 0, "save result wrote after storage read failed");
  const deleteResult = deleteSavedPersonaResult("x", failingReadStorage);
  assert(deleteResult.ok === false, "delete reported success after storage read failed");
  assert(writes === 0, "delete wrote after storage read failed");

  console.error("savedPersonas selfCheck OK");
}
