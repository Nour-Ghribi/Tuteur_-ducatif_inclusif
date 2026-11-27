import { useEffect, useMemo, useState } from "react";
import { PreferencesPanel } from "./a11y/PreferencesPanel";
import { PreferencesProvider, usePreferences } from "./a11y/PreferencesContext";
import { ActionsContext, type Actions } from "./api/ActionsContext";
import { api, tokenStore } from "./api/client";
import {
  SUPPORTED_LANGUAGES,
  type SupportedLanguage,
  RTL_LANGUAGES,
  setAppLanguage,
  t,
} from "./i18n";
import { OnboardingPage } from "./pages/OnboardingPage";
import { StudentPage } from "./pages/StudentPage";
import { TeacherPage } from "./pages/TeacherPage";
import { ParentPage } from "./pages/ParentPage";
import { ProgressPage } from "./pages/ProgressPage";

// ---------------------------------------------------------------------------
// Dev token panel (development only)
// ---------------------------------------------------------------------------
function DevToken() {
  const [token, setToken] = useState(tokenStore.get());
  const [saved, setSaved] = useState(false);
  return (
    <details className="panel">
      <summary>{t("dev.title")}</summary>
      <p className="muted">{t("dev.help")}</p>
      <label className="field">
        <span>{t("dev.token")}</span>
        <input
          type="password"
          autoComplete="off"
          value={token}
          onChange={(e) => { setToken(e.target.value); setSaved(false); }}
        />
      </label>
      <button
        type="button"
        onClick={() => { tokenStore.set(token.trim()); setSaved(true); }}
      >
        {t("dev.save")}
      </button>
      <p role="status">{saved && t("dev.saved")}</p>
    </details>
  );
}

// ---------------------------------------------------------------------------
// Language selector
// ---------------------------------------------------------------------------
const LANG_LABELS: Record<SupportedLanguage, string> = {
  fr: "Français",
  ar: "العربية",
  en: "English",
};

function LanguageSelector({
  current,
  onChange,
}: {
  current: SupportedLanguage;
  onChange: (lang: SupportedLanguage) => void;
}) {
  return (
    <label className="lang-selector" aria-label="Langue de l'interface">
      <select
        value={current}
        onChange={(e) => onChange(e.target.value as SupportedLanguage)}
      >
        {SUPPORTED_LANGUAGES.map((l) => (
          <option key={l} value={l}>
            {LANG_LABELS[l]}
          </option>
        ))}
      </select>
    </label>
  );
}

// ---------------------------------------------------------------------------
// App shell
// ---------------------------------------------------------------------------
type View = "student" | "teacher" | "parent" | "progress";

function Shell() {
  const { preferences } = usePreferences();
  const [view, setView] = useState<View>("student");
  const [language, setLanguage] = useState<SupportedLanguage>("fr");

  // Onboarding: shown once per session if not already done
  const [onboardingDone, setOnboardingDone] = useState<boolean>(
    () => !!sessionStorage.getItem("tutor.onboarding.done"),
  );

  // Sync language → document direction + HTML lang
  useEffect(() => {
    setAppLanguage(language);
  }, [language]);

  const actions = useMemo<Actions>(
    () => ({
      submitAnswer: (questionId, answer) => api.submitAnswer(questionId, answer, preferences),
      reportOutcome: (id, outcome) => api.reportOutcome(id, outcome),
      loadAsset: (id) => api.assetUrl(id),
    }),
    [preferences],
  );

  // Show onboarding wizard for new students (student view only)
  if (!onboardingDone && view === "student") {
    return (
      <ActionsContext.Provider value={actions}>
        <OnboardingPage onDone={() => setOnboardingDone(true)} />
      </ActionsContext.Provider>
    );
  }

  const NAV_VIEWS: { key: View; label: string }[] = [
    { key: "student",  label: t("nav.student") },
    { key: "teacher",  label: t("nav.teacher") },
    { key: "parent",   label: t("nav.parent") },
    { key: "progress", label: t("form.progress") },
  ];

  return (
    <ActionsContext.Provider value={actions}>
      <a href="#main" className="skip-link">
        {t("app.skip")}
      </a>
      <header>
        <h1>{t("app.title")}</h1>
        <nav aria-label={t("nav.label")}>
          {NAV_VIEWS.map(({ key, label }) => (
            <button
              key={key}
              type="button"
              className={view === key ? "tab active" : "tab"}
              aria-current={view === key ? "page" : undefined}
              onClick={() => setView(key)}
            >
              {label}
            </button>
          ))}
        </nav>
        <LanguageSelector current={language} onChange={setLanguage} />
      </header>
      <main id="main">
        {view === "student"  && <StudentPage />}
        {view === "teacher"  && <TeacherPage />}
        {view === "parent"   && <ParentPage />}
        {view === "progress" && <ProgressPage />}
        <PreferencesPanel />
        <DevToken />
      </main>
    </ActionsContext.Provider>
  );
}

// ---------------------------------------------------------------------------
// Root
// ---------------------------------------------------------------------------
export default function App() {
  return (
    <PreferencesProvider>
      <Shell />
    </PreferencesProvider>
  );
}
