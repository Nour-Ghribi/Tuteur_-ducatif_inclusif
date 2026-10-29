import { useId, useState } from "react";
import { useActions } from "../api/ActionsContext";
import { t, translateCode } from "../i18n";
import type { BlockOf } from "../ui-schema/schema";

const percent = (ratio: number) => `${Math.round(ratio * 100)} %`;

export function Progress({ block }: { block: BlockOf<"progress"> }) {
  const labelId = useId();
  const label = translateCode(t, "label", block.label_code);
  return (
    <div className="progress">
      <span id={labelId}>{label}</span>
      <progress value={block.value} max={1} aria-labelledby={labelId} aria-valuetext={percent(block.value)} />
      <span aria-hidden="true">{percent(block.value)}</span>
    </div>
  );
}

export function MetricGrid({ block }: { block: BlockOf<"metric_grid"> }) {
  return (
    <dl className="metrics">
      {block.metrics.map((metric, i) => (
        <div key={i} className="metric">
          <dt>{translateCode(t, "label", metric.label_code)}</dt>
          <dd>
            {metric.unit === "ratio"
              ? percent(metric.value)
              : metric.unit === "seconds"
                ? `${Math.round(metric.value)} s`
                : metric.value}
          </dd>
        </div>
      ))}
    </dl>
  );
}

/** Bars are decorative; the table carries the data for every user. */
export function BarChart({ block }: { block: BlockOf<"bar_chart"> }) {
  const max = Math.max(...block.bars.map((b) => b.value), block.value_unit === "ratio" ? 1 : 0.0001);
  const format = (value: number) => (block.value_unit === "ratio" ? percent(value) : String(value));
  return (
    <div className="table-wrap" tabIndex={0} role="region" aria-label={translateCode(t, "label", block.title_code)}>
      <table className="bars">
        <caption>{translateCode(t, "label", block.title_code)}</caption>
        <thead>
          <tr>
            <th scope="col">{t("table.compare")}</th>
            <th scope="col">{t("chart.value")}</th>
          </tr>
        </thead>
        <tbody>
          {block.bars.map((bar, i) => (
            <tr key={i}>
              <th scope="row">{bar.label}</th>
              <td>
                <span className="bar" style={{ width: `${(bar.value / max) * 100}%` }} aria-hidden="true" />
                {format(bar.value)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function RecommendationCard({ block }: { block: BlockOf<"recommendation_card"> }) {
  const actions = useActions();
  const [state, setState] = useState<"idle" | "sending" | "done" | "error">("idle");

  async function report(completed: boolean) {
    if (!actions) return;
    setState("sending");
    try {
      await actions.reportOutcome(block.recommendation_id, { completed });
      setState("done");
    } catch {
      setState("error");
    }
  }

  return (
    <article className="card recommendation">
      <h3>{t("rec.title")}</h3>
      <p>
        <strong>{t(`activity.${block.activity_type}`)}</strong> — {t(`difficulty.${block.difficulty}`)} —{" "}
        {block.topic}
      </p>
      {block.rationale && <p className="muted">{block.rationale}</p>}
      {block.source === "fallback" && <p className="muted">{t("rec.fallback")}</p>}
      <div className="row">
        <button type="button" onClick={() => report(true)} disabled={!actions || state === "sending" || state === "done"}>
          {t("rec.done")}
        </button>
        <button type="button" onClick={() => report(false)} disabled={!actions || state === "sending" || state === "done"}>
          {t("rec.skip")}
        </button>
      </div>
      <p role="status" aria-live="polite">
        {state === "done" && t("rec.thanks")}
        {state === "error" && t("rec.failed")}
      </p>
    </article>
  );
}
