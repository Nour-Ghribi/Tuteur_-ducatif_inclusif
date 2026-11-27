/**
 * EngagementRadar — renders an EngagementBlock.
 *
 * Shows curiosity, persistence and autonomy as three horizontal progress bars
 * with tier labels (low / medium / high). A proper SVG radar chart can replace
 * this later; the bar version is fully accessible now.
 *
 * Screen readers get the score and tier for each axis via aria-label.
 */
import { t } from "../i18n";
import type { BlockOf } from "../ui-schema/schema";

type Axis = BlockOf<"engagement">["axes"][number];

const TIER_COLOR: Record<string, string> = {
  low:    "var(--muted)",
  medium: "var(--accent)",
  high:   "var(--ok)",
};

function EngagementAxis({ axis }: { axis: Axis }) {
  const label = t(`progress.${axis.label_code}` as never) ?? axis.label_code;
  const tierLabel = t(`progress.tier.${axis.tier}` as never) ?? axis.tier;
  const pct = Math.round(axis.score * 100);

  return (
    <div
      className="engagement-axis"
      aria-label={`${label} : ${pct}% — ${tierLabel}`}
    >
      <div className="engagement-axis-header">
        <span className="engagement-axis-label">{label}</span>
        <span className="engagement-axis-tier" style={{ color: TIER_COLOR[axis.tier] }}>
          {tierLabel}
        </span>
      </div>
      <div className="engagement-bar-track" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
        <div
          className="engagement-bar-fill"
          style={{
            width: `${pct}%`,
            background: TIER_COLOR[axis.tier],
          }}
        />
      </div>
      <span className="engagement-pct" aria-hidden="true">{pct}%</span>
    </div>
  );
}

export function EngagementRadar({ block }: { block: BlockOf<"engagement"> }) {
  return (
    <section className="engagement-radar" aria-label={t("progress.engagement")}>
      <h3>{t("progress.engagement")}</h3>
      {block.sessions_used > 0 && (
        <p className="muted" style={{ fontSize: "0.85rem" }}>
          Basé sur {block.sessions_used} session{block.sessions_used > 1 ? "s" : ""}
        </p>
      )}
      <div className="engagement-axes">
        {block.axes.map((axis, i) => (
          <EngagementAxis key={i} axis={axis} />
        ))}
      </div>
    </section>
  );
}
