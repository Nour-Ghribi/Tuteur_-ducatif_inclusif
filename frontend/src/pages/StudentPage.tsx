import { useEffect, useRef, useState, type FormEvent } from "react";
import { usePreferences } from "../a11y/PreferencesContext";
import { ApiError, api } from "../api/client";
import { t } from "../i18n";
import type { MessageKey } from "../i18n";
import { UISpecRenderer } from "../renderer/UISpecRenderer";
import type { TutorResponse } from "../ui-schema/schema";

const FORMATS = ["explanation", "quiz", "flashcards", "concept_cards", "concept_map", "steps", "comparison"] as const;

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 0) return t("error.network");
    const key = `error.${error.status}` as MessageKey;
    return t(key) !== key ? t(key) : t("error.generic");
  }
  return t("error.generic");
}

export function StudentPage() {
  const { preferences } = usePreferences();
  const [course, setCourse] = useState("demo-bio-101");
  const [topic, setTopic] = useState("");
  const [message, setMessage] = useState("");
  const [format, setFormat] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [response, setResponse] = useState<TutorResponse | null>(null);
  const resultRef = useRef<HTMLElement>(null);

  // Moving focus to the new result lets keyboard and screen-reader users land on it.
  useEffect(() => {
    if (response) resultRef.current?.focus();
  }, [response]);

  async function run(task: () => Promise<TutorResponse>) {
    setBusy(true);
    setError(null);
    try {
      setResponse(await task());
    } catch (e) {
      setResponse(null);
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    void run(() =>
      api.createExperience({ message, course_id: course, topic, requested_format: format, preferences }),
    );
  }

  return (
    <>
      <form onSubmit={onSubmit} className="panel">
        <label className="field">
          <span>{t("form.course")}</span>
          <input value={course} onChange={(e) => setCourse(e.target.value)} required maxLength={64} />
        </label>
        <label className="field">
          <span>{t("form.topic")}</span>
          <input value={topic} onChange={(e) => setTopic(e.target.value)} maxLength={200} />
        </label>
        <label className="field">
          <span>{t("form.message")}</span>
          <textarea
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            placeholder={t("form.message.placeholder")}
            required
            maxLength={2000}
            rows={3}
          />
        </label>
        <label className="field">
          <span>{t("form.format")}</span>
          <select value={format} onChange={(e) => setFormat(e.target.value)}>
            <option value="">{t("form.format.auto")}</option>
            {FORMATS.map((f) => (
              <option key={f} value={f}>
                {t(`format.${f}`)}
              </option>
            ))}
          </select>
        </label>
        <div className="row">
          <button type="submit" disabled={busy || !message.trim()}>
            {busy ? t("form.sending") : t("form.send")}
          </button>
          <button type="button" className="secondary" disabled={busy} onClick={() => void run(api.progress)}>
            {t("form.progress")}
          </button>
        </div>
      </form>

      {error && (
        <p role="alert" className="callout callout-error">
          {error}
        </p>
      )}
      {response && (
        <section ref={resultRef} tabIndex={-1} aria-labelledby="result-title" className="result">
          <h2 id="result-title">{t("result.title")}</h2>
          <UISpecRenderer ui={response.ui} />
        </section>
      )}
    </>
  );
}
