/**
 * Accessibility preferences declared by the user (or an authorized application setting).
 * They are never inferred from behaviour; the same object is sent to the backend with each request.
 */
export type ColorVision = "none" | "protanopia" | "deuteranopia" | "tritanopia";

export interface Preferences {
  simplified_language: boolean;
  short_segments: boolean;
  reduced_visual_complexity: boolean;
  screen_reader_optimized: boolean;
  high_contrast: boolean;
  color_vision: ColorVision;
  text_scale: number;
}

export const DEFAULT_PREFERENCES: Preferences = {
  simplified_language: false,
  short_segments: false,
  reduced_visual_complexity: false,
  screen_reader_optimized: false,
  high_contrast: false,
  color_vision: "none",
  text_scale: 1,
};

const STORAGE_KEY = "tutor.preferences.v1";
const COLOR_VISIONS: ColorVision[] = ["none", "protanopia", "deuteranopia", "tritanopia"];

/** Defensive parse: storage can be empty, blocked or edited by hand. */
export function sanitizePreferences(raw: unknown): Preferences {
  const r = (typeof raw === "object" && raw !== null ? raw : {}) as Record<string, unknown>;
  const flag = (name: keyof Preferences) => (typeof r[name] === "boolean" ? (r[name] as boolean) : false);
  const scale = typeof r.text_scale === "number" ? Math.min(2, Math.max(1, r.text_scale)) : 1;
  return {
    simplified_language: flag("simplified_language"),
    short_segments: flag("short_segments"),
    reduced_visual_complexity: flag("reduced_visual_complexity"),
    screen_reader_optimized: flag("screen_reader_optimized"),
    high_contrast: flag("high_contrast"),
    color_vision: COLOR_VISIONS.includes(r.color_vision as ColorVision) ? (r.color_vision as ColorVision) : "none",
    text_scale: scale,
  };
}

export function loadPreferences(): Preferences {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    return sanitizePreferences(stored ? JSON.parse(stored) : null);
  } catch {
    return DEFAULT_PREFERENCES;
  }
}

export function savePreferences(preferences: Preferences): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(preferences));
  } catch {
    /* storage unavailable: preferences simply last for this page view */
  }
}
