/**
 * ParentPage — progress report for a parent or supervisor.
 *
 * Calls POST /api/v1/parent/reports and renders the resulting UISpec.
 * Provides a "Download PDF" button that calls GET /parent/reports/{id}/pdf.
 */
import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import { t } from "../i18n";
import { UISpecRenderer } from "../renderer/UISpecRenderer";
import type { TutorResponse } from "../ui-schema/schema";
import { errorMessage } from "./StudentPage";

const isoDay = (date: Date) => date.toISOString().slice(0, 10);

export function ParentPage() {
  const today = new Date();
  const [studentRef, setStudentRef] = useState("");
  const [start, setStart] = useState(isoDay(new Date(today.getTime() - 30 * 86_400_000)));
  const [end, setEnd] = useState(isoDay(today));
  const [language, setLanguage] = useState("fr");
  const [busy, setBusy] = useState(false);
  const [pdfBusy, setPdfBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [response, setResponse] = useState<TutorResponse | null>(null);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await api.parentReport({
        student_ref: studentRef,
        period_start: start,
        period_end: end,
        language: language || undefined,
      });
      setResponse(result);
    } catch (e) {
      setResponse(null);
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  async function downloadPdf() {
    if (!response) return;
    setPdfBusy(true);
    try {
      await api.downloadParentReportPdf(response.request_id);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setPdfBusy(false);
    }
  }

  return (
    <>
      <form onSubmit={onSubmit} className="panel">
        <h2>{t("parent.title")}</h2>
        <p className="muted">{t("parent.note")}</p>
        <label className="field">
          <span>{t("parent.student_ref")}</span>
          <input
            value={studentRef}
            onChange={(e) => setStudentRef(e.target.value)}
            required
            maxLength={64}
            placeholder="student-dev-1"
          />
        </label>
        <label className="field">
          <span>{t("parent.start")}</span>
          <input
            type="date"
            value={start}
            max={end}
            onChange={(e) => setStart(e.target.value)}
            required
          />
        </label>
        <label className="field">
          <span>{t("parent.end")}</span>
          <input
            type="date"
            value={end}
            min={start}
            max={isoDay(today)}
            onChange={(e) => setEnd(e.target.value)}
            required
          />
        </label>
        <label className="field">
          <span>Langue du rapport</span>
          <select value={language} onChange={(e) => setLanguage(e.target.value)}>
            <option value="fr">Français</option>
            <option value="ar">العربية</option>
            <option value="en">English</option>
          </select>
        </label>
        <button type="submit" disabled={busy}>
          {busy ? t("form.sending") : t("parent.send")}
        </button>
      </form>

      {error && (
        <p role="alert" className="callout callout-error">
          {error}
        </p>
      )}

      {response && (
        <section aria-labelledby="parent-report-title" className="result">
          <h2 id="parent-report-title">{t("parent.title")}</h2>
          <UISpecRenderer ui={response.ui} />
          <button
            onClick={downloadPdf}
            disabled={pdfBusy}
            className="btn-secondary"
            style={{ marginTop: "1rem" }}
          >
            {pdfBusy ? t("form.sending") : t("parent.download_pdf")}
          </button>
        </section>
      )}
    </>
  );
}
