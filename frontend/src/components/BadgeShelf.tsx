/**
 * BadgeShelf — renders a BadgeShelfBlock or BadgeToastBlock.
 *
 * Visual row of earned badges. Each badge shows an icon (emoji/text fallback),
 * a label, a tier coloured dot, and an optional earned date in a tooltip.
 * Screen readers get the full label + tier announced.
 *
 * The toast variant (newly earned badges) renders with a success callout.
 */
import { t } from "../i18n";
import type { BlockOf } from "../ui-schema/schema";

type BadgeView = BlockOf<"badge_shelf">["badges"][number];

const TIER_ICON: Record<string, string> = {
  bronze: "🥉",
  silver: "🥈",
  gold:   "🥇",
  special: "⭐",
};

function BadgeCard({ badge }: { badge: BadgeView }) {
  const tierLabel = t(`badge.tier.${badge.tier}` as never) ?? badge.tier;
  return (
    <li
      className={`badge-card badge-tier-${badge.tier}`}
      title={badge.earned_at ? `Obtenu le ${badge.earned_at}` : undefined}
      aria-label={`${badge.label} — ${tierLabel}`}
    >
      <span className="badge-icon" aria-hidden="true">
        {TIER_ICON[badge.tier] ?? "🏅"}
      </span>
      <span className="badge-label">{badge.label}</span>
      <span className="badge-tier-dot" aria-hidden="true" />
    </li>
  );
}

export function BadgeShelf({ block }: { block: BlockOf<"badge_shelf"> }) {
  if (!block.badges.length) {
    return <p className="muted">{t("progress.no_badges")}</p>;
  }
  return (
    <section aria-label={t("progress.earned_badges")}>
      <h3>{t("progress.earned_badges")}</h3>
      <ul className="badge-shelf">
        {block.badges.map((b, i) => <BadgeCard key={i} badge={b} />)}
      </ul>
    </section>
  );
}

export function BadgeToast({ block }: { block: BlockOf<"badge_toast"> }) {
  return (
    <div className="callout callout-success badge-toast" role="status" aria-live="polite">
      <span className="callout-icon" aria-hidden="true">🎉</span>
      <div>
        <p><strong>Nouveau badge obtenu !</strong></p>
        <ul className="badge-shelf badge-shelf-compact">
          {block.badges.map((b, i) => <BadgeCard key={i} badge={b} />)}
        </ul>
      </div>
    </div>
  );
}
