import { useId } from "react";
import { t } from "../i18n";
import { usePreferences } from "./PreferencesContext";
import type { ColorVision, Preferences } from "./preferences";

const TOGGLES = [
  "simplified_language",
  "short_segments",
  "reduced_visual_complexity",
  "screen_reader_optimized",
  "high_contrast",
] as const satisfies readonly (keyof Preferences)[];

const AUDIO_TOGGLES = [
  "audio_enabled",
  "karaoke_mode",
] as const satisfies readonly (keyof Preferences)[];

const COLORS: ColorVision[] = ["none", "protanopia", "deuteranopia", "tritanopia"];

export function PreferencesPanel() {
  const { preferences, setPreferences } = usePreferences();
  const helpId = useId();
  const set = <K extends keyof Preferences>(key: K, value: Preferences[K]) =>
    setPreferences({ ...preferences, [key]: value });

  return (
    <fieldset className="prefs" aria-describedby={helpId}>
      <legend>{t("prefs.title")}</legend>
      <p id={helpId} className="muted">
        {t("prefs.help")}
      </p>
      {TOGGLES.map((key) => (
        <label key={key} className="check">
          <input
            type="checkbox"
            checked={preferences[key]}
            onChange={(e) => set(key, e.target.checked)}
          />
          <span>{t(`prefs.${key}`)}</span>
        </label>
      ))}
      <label className="field">
        <span>{t("prefs.color_vision")}</span>
        <select
          value={preferences.color_vision}
          onChange={(e) => set("color_vision", e.target.value as ColorVision)}
        >
          {COLORS.map((c) => (
            <option key={c} value={c}>
              {t(`color.${c}`)}
            </option>
          ))}
        </select>
      </label>
      <label className="field">
        <span>
          {t("prefs.text_scale")} ({Math.round(preferences.text_scale * 100)} %)
        </span>
        <input
          type="range"
          min={1}
          max={2}
          step={0.25}
          value={preferences.text_scale}
          onChange={(e) => set("text_scale", Number(e.target.value))}
        />
      </label>

      {/* Audio section */}
      <fieldset className="prefs-section">
        <legend>{t("prefs.audio_section")}</legend>
        {AUDIO_TOGGLES.map((key) => (
          <label key={key} className="check">
            <input
              type="checkbox"
              checked={preferences[key]}
              onChange={(e) => set(key, e.target.checked)}
            />
            <span>{t(`prefs.${key}`)}</span>
          </label>
        ))}
        {preferences.audio_enabled && (
          <label className="field">
            <span>
              {t("prefs.audio_speed")} ({preferences.audio_speed.toFixed(1)}×)
            </span>
            <input
              type="range"
              min={0.5}
              max={2.0}
              step={0.25}
              value={preferences.audio_speed}
              onChange={(e) => set("audio_speed", Number(e.target.value))}
            />
          </label>
        )}
      </fieldset>
    </fieldset>
  );
}
