import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import { t } from "../i18n";
import { UISpecRenderer } from "../renderer/UISpecRenderer";
import type { TutorResponse } from "../ui-schema/schema";
import { errorMessage } from "./StudentPage";

const isoDay = (date: Date) => date.toISOString().slice(0, 10);

export function TeacherPage() {
  const today = new Date();
  const [classId, setClassId] = useState("class-demo-a");
  const [start, setStart] = useState(isoDay(new Date(today.getTime() - 30 * 86_400_000)));
  const [end, setEnd] = useState(isoDay(today));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [response, setResponse] = useState<TutorResponse | null>(null);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setResponse(await api.teacherReport({ class_id: classId, period_start: start, period_end: end }));
    } catch (e) {
      setResponse(null);
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <form onSubmit={onSubmit} className="panel">
        <h2>{t("teacher.title")}</h2>
        <p className="muted">{t("teacher.note")}</p>
        <label className="field">
          <span>{t("teacher.class")}</span>
          <input value={classId} onChange={(e) => setClassId(e.target.value)} required maxLength={64} />
        </label>
        <label className="field">
          <span>{t("teacher.start")}</span>
          <input type="date" value={start} max={end} onChange={(e) => setStart(e.target.value)} required />
        </label>
        <label className="field">
          <span>{t("teacher.end")}</span>
          <input type="date" value={end} min={start} max={isoDay(today)} onChange={(e) => setEnd(e.target.value)} required />
        </label>
        <button type="submit" disabled={busy}>
          {busy ? t("form.sending") : t("teacher.send")}
        </button>
      </form>
      {error && (
        <p role="alert" className="callout callout-error">
          {error}
        </p>
      )}
      {response && (
        <section aria-labelledby="report-title" className="result">
          <h2 id="report-title">{t("result.title")}</h2>
          <UISpecRenderer ui={response.ui} />
        </section>
      )}
    </>
  );
}
