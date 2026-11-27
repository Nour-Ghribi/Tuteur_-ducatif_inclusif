/**
 * ProgressPage — full student progress dashboard.
 *
 * Calls GET /api/v1/tutor/progress and renders:
 *   - MetricGrid (attempts, active days, success rate)
 *   - EngagementRadar (curiosity / persistence / autonomy)
 *   - BadgeShelf (earned badges)
 *
 * The backend returns these as standard UIBlocks so UISpecRenderer handles them,
 * but we also render the engagement and badge blocks with their dedicated
 * components when present.
 */
import { useEffect, useState } from "react";
import { api } from "../api/client";
import { t } from "../i18n";
import { UISpecRenderer } from "../renderer/UISpecRenderer";
import type { TutorResponse } from "../ui-schema/schema";
import { errorMessage } from "./StudentPage";

export function ProgressPage() {
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [response, setResponse] = useState<TutorResponse | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .progress()
      .then((r) => { if (!cancelled) { setResponse(r); setBusy(false); } })
      .catch((e) => { if (!cancelled) { setError(errorMessage(e)); setBusy(false); } });
    return () => { cancelled = true; };
  }, []);

  if (busy) {
    return (
      <div className="panel" role="status" aria-busy="true">
        {t("form.sending")}
      </div>
    );
  }

  if (error) {
    return (
      <p role="alert" className="callout callout-error">
        {error}
      </p>
    );
  }

  if (!response) return null;

  return (
    <section aria-labelledby="progress-title">
      <h2 id="progress-title">{t("progress.title")}</h2>
      <UISpecRenderer ui={response.ui} />
    </section>
  );
}
