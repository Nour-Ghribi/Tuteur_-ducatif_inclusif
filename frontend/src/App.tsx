import { useMemo, useState } from "react";
import { PreferencesPanel } from "./a11y/PreferencesPanel";
import { PreferencesProvider, usePreferences } from "./a11y/PreferencesContext";
import { ActionsContext, type Actions } from "./api/ActionsContext";
import { api, tokenStore } from "./api/client";
import { t } from "./i18n";
import { StudentPage } from "./pages/StudentPage";
import { TeacherPage } from "./pages/TeacherPage";

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
          onChange={(e) => {
            setToken(e.target.value);
            setSaved(false);
          }}
        />
      </label>
      <button
        type="button"
        onClick={() => {
          tokenStore.set(token.trim());
          setSaved(true);
        }}
      >
        {t("dev.save")}
      </button>
      <p role="status">{saved && t("dev.saved")}</p>
    </details>
  );
}

function Shell() {
  const { preferences } = usePreferences();
  const [view, setView] = useState<"student" | "teacher">("student");
  const actions = useMemo<Actions>(
    () => ({
      submitAnswer: (questionId, answer) => api.submitAnswer(questionId, answer, preferences),
      reportOutcome: (id, outcome) => api.reportOutcome(id, outcome),
      loadAsset: (id) => api.assetUrl(id),
    }),
    [preferences],
  );

  return (
    <ActionsContext.Provider value={actions}>
      <a href="#main" className="skip-link">
        {t("app.skip")}
      </a>
      <header>
        <h1>{t("app.title")}</h1>
        <nav aria-label={t("nav.label")}>
          {(["student", "teacher"] as const).map((v) => (
            <button
              key={v}
              type="button"
              className={view === v ? "tab active" : "tab"}
              aria-current={view === v ? "page" : undefined}
              onClick={() => setView(v)}
            >
              {t(`nav.${v}`)}
            </button>
          ))}
        </nav>
      </header>
      <main id="main">
        {view === "student" ? <StudentPage /> : <TeacherPage />}
        <PreferencesPanel />
        <DevToken />
      </main>
    </ActionsContext.Provider>
  );
}

export default function App() {
  return (
    <PreferencesProvider>
      <Shell />
    </PreferencesProvider>
  );
}
