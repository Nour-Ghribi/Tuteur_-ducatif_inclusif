/**
 * OnboardingPage — 4-step wizard for student profile setup.
 *
 * Steps:
 *   1. Age group + school level
 *   2. Special needs (cognitive, vision, hearing)
 *   3. Language preference
 *   4. Preview (shows what will be auto-enabled) + confirm
 *
 * On completion, calls POST /api/v1/profile and stores a flag in
 * sessionStorage so the app doesn't show it again this session.
 * The student can skip — a default profile is not saved, preferences
 * fall back to in-memory defaults.
 */
import { useState } from "react";
import { api, tokenStore } from "../api/client";
import { t } from "../i18n";
import type { ApiError } from "../api/client";

export interface OnboardingDone {
  skipped: boolean;
}

interface Props {
  onDone: (result: OnboardingDone) => void;
}

// Options mirroring backend profile enums
const AGE_GROUPS = [
  { value: "child",      label: "Enfant (6–11 ans)" },
  { value: "middle",     label: "Collège (12–14 ans)" },
  { value: "high",       label: "Lycée (15–18 ans)" },
  { value: "university", label: "Université (18+)" },
  { value: "adult",      label: "Adulte (formation continue)" },
] as const;

const SCHOOL_LEVELS = [
  { value: "primary",        label: "Primaire" },
  { value: "middle",         label: "Collège" },
  { value: "high",           label: "Lycée" },
  { value: "university",     label: "Université" },
  { value: "adult_learning", label: "Formation continue" },
] as const;

const COGNITIVE_NEEDS = [
  { value: "none",        label: t("onboarding.none") },
  { value: "dyslexia",   label: "Dyslexie" },
  { value: "adhd",       label: "TDAH" },
  { value: "add",        label: "TDA" },
  { value: "autism",     label: "Autisme" },
  { value: "dyscalculia",label: "Dyscalculie" },
] as const;

const VISION_NEEDS = [
  { value: "none",          label: t("onboarding.none") },
  { value: "low_vision",    label: "Basse vision" },
  { value: "protanopia",    label: "Protanopie (rouge)" },
  { value: "deuteranopia",  label: "Deutéranopie (vert)" },
  { value: "tritanopia",    label: "Tritanopie (bleu)" },
  { value: "blind",         label: "Non-voyant" },
] as const;

const HEARING_NEEDS = [
  { value: "none",             label: t("onboarding.none") },
  { value: "hard_of_hearing",  label: "Malentendant" },
  { value: "deaf",             label: "Sourd" },
] as const;

const LANGUAGES = [
  { value: "fr", label: "Français" },
  { value: "ar", label: "العربية" },
  { value: "en", label: "English" },
] as const;

type Step = 1 | 2 | 3 | 4;

export function OnboardingPage({ onDone }: Props) {
  const [step, setStep] = useState<Step>(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Form state
  const [ageGroup, setAgeGroup] = useState<string>("middle");
  const [schoolLevel, setSchoolLevel] = useState<string>("middle");
  const [cognitiveNeed, setCognitiveNeed] = useState<string>("none");
  const [visionNeed, setVisionNeed] = useState<string>("none");
  const [hearingNeed, setHearingNeed] = useState<string>("none");
  const [language, setLanguage] = useState<string>("fr");

  // Derive auto-activated preferences for step 4 preview
  const autoPrefs: string[] = [];
  if (cognitiveNeed === "dyslexia") autoPrefs.push("Texte simplifié, audio + karaoké");
  if (cognitiveNeed === "adhd" || cognitiveNeed === "add") autoPrefs.push("Segments courts, audio");
  if (cognitiveNeed === "autism") autoPrefs.push("Affichage épuré, contraste élevé");
  if (visionNeed === "blind") autoPrefs.push("Lecteur d'écran, audio");
  if (visionNeed === "low_vision") autoPrefs.push("Texte agrandi, contraste élevé");
  if (visionNeed !== "none" && visionNeed !== "blind" && visionNeed !== "low_vision") autoPrefs.push(`Adaptation couleurs (${visionNeed})`);
  if (hearingNeed !== "none") autoPrefs.push("Texte simplifié");
  if (autoPrefs.length === 0) autoPrefs.push("Paramètres par défaut");

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      await api.createProfile({
        age_group: ageGroup,
        school_level: schoolLevel,
        cognitive_need: cognitiveNeed,
        vision_need: visionNeed,
        hearing_need: hearingNeed,
        language_preference: language,
      });
      sessionStorage.setItem("tutor.onboarding.done", "1");
      onDone({ skipped: false });
    } catch (e) {
      const err = e as ApiError;
      setError(err?.message || "Une erreur est survenue.");
    } finally {
      setBusy(false);
    }
  }

  function skip() {
    sessionStorage.setItem("tutor.onboarding.done", "1");
    onDone({ skipped: true });
  }

  const STEP_LABELS: Record<Step, string> = {
    1: t("onboarding.step_age"),
    2: t("onboarding.step_needs"),
    3: t("onboarding.step_language"),
    4: t("onboarding.step_preview"),
  };

  return (
    <div className="onboarding panel" role="main" aria-label={t("onboarding.title")}>
      {/* Header */}
      <h1>{t("onboarding.title")}</h1>
      <p className="muted">{t("onboarding.subtitle")}</p>

      {/* Step indicator */}
      <nav className="onboarding-steps" aria-label="Étapes">
        {([1, 2, 3, 4] as Step[]).map((s) => (
          <span
            key={s}
            className={`onboarding-step ${s === step ? "active" : s < step ? "done" : ""}`}
            aria-current={s === step ? "step" : undefined}
          >
            {s}. {STEP_LABELS[s]}
          </span>
        ))}
      </nav>

      {/* Step 1: Age + level */}
      {step === 1 && (
        <fieldset>
          <legend>{t("onboarding.step_age")}</legend>
          <label className="field">
            <span>{t("onboarding.age_group")}</span>
            <select value={ageGroup} onChange={(e) => setAgeGroup(e.target.value)}>
              {AGE_GROUPS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </label>
          <label className="field">
            <span>{t("onboarding.school_level")}</span>
            <select value={schoolLevel} onChange={(e) => setSchoolLevel(e.target.value)}>
              {SCHOOL_LEVELS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </label>
        </fieldset>
      )}

      {/* Step 2: Special needs */}
      {step === 2 && (
        <fieldset>
          <legend>{t("onboarding.step_needs")}</legend>
          <label className="field">
            <span>{t("onboarding.cognitive_need")}</span>
            <select value={cognitiveNeed} onChange={(e) => setCognitiveNeed(e.target.value)}>
              {COGNITIVE_NEEDS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </label>
          <label className="field">
            <span>{t("onboarding.vision_need")}</span>
            <select value={visionNeed} onChange={(e) => setVisionNeed(e.target.value)}>
              {VISION_NEEDS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </label>
          <label className="field">
            <span>{t("onboarding.hearing_need")}</span>
            <select value={hearingNeed} onChange={(e) => setHearingNeed(e.target.value)}>
              {HEARING_NEEDS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </label>
        </fieldset>
      )}

      {/* Step 3: Language */}
      {step === 3 && (
        <fieldset>
          <legend>{t("onboarding.step_language")}</legend>
          <div className="onboarding-lang-grid" role="radiogroup" aria-label={t("onboarding.language_pref")}>
            {LANGUAGES.map((l) => (
              <label key={l.value} className={`lang-card ${language === l.value ? "selected" : ""}`}>
                <input
                  type="radio"
                  name="language"
                  value={l.value}
                  checked={language === l.value}
                  onChange={() => setLanguage(l.value)}
                  className="sr-only"
                />
                <span className="lang-label">{l.label}</span>
              </label>
            ))}
          </div>
        </fieldset>
      )}

      {/* Step 4: Preview */}
      {step === 4 && (
        <div className="onboarding-preview">
          <p>{t("onboarding.preview_text")}</p>
          <ul className="onboarding-preview-list">
            {autoPrefs.map((p, i) => <li key={i}>✓ {p}</li>)}
          </ul>
        </div>
      )}

      {/* Error */}
      {error && <p role="alert" className="callout callout-error">{error}</p>}

      {/* Navigation */}
      <div className="onboarding-nav row">
        {step > 1 && (
          <button type="button" className="secondary" onClick={() => setStep((s) => (s - 1) as Step)}>
            {t("onboarding.back")}
          </button>
        )}
        {step < 4 && (
          <button type="button" onClick={() => setStep((s) => (s + 1) as Step)}>
            {t("onboarding.next")}
          </button>
        )}
        {step === 4 && (
          <button type="button" onClick={submit} disabled={busy}>
            {busy ? t("form.sending") : t("onboarding.finish")}
          </button>
        )}
        <button type="button" className="secondary" onClick={skip}>
          {t("onboarding.skip")}
        </button>
      </div>
    </div>
  );
}
