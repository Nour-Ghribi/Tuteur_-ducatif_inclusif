import { hasCode, t, translateCode, type MessageKey } from "../i18n";
import { BulletList, Callout, Heading, Text } from "../components/TextBlocks";
import {
  ComparisonTable,
  ConceptCards,
  FlashcardDeck,
  Quiz,
  QuizFeedback,
  Steps,
} from "../components/Learning";
import { ConceptMap } from "../components/ConceptMap";
import { BarChart, MetricGrid, Progress, RecommendationCard } from "../components/Report";
import { FallbackView, ImageFigure, UnknownBlock } from "../components/Media";
import type { ParsedUI, UIBlock, UIMeta } from "../ui-schema/schema";

/**
 * The only place that maps block types to components. A type that is not listed here can never be
 * rendered, whatever the backend (or a model) sends: it falls through to UnknownBlock.
 */
export function BlockView({ block }: { block: UIBlock }) {
  switch (block.type) {
    case "heading":
      return <Heading block={block} />;
    case "text":
      return <Text block={block} />;
    case "bullet_list":
      return <BulletList block={block} />;
    case "callout":
      return <Callout block={block} />;
    case "flashcard_deck":
      return <FlashcardDeck block={block} />;
    case "quiz":
      return <Quiz block={block} />;
    case "quiz_feedback":
      return <QuizFeedback block={block} />;
    case "concept_cards":
      return <ConceptCards block={block} />;
    case "steps":
      return <Steps block={block} />;
    case "comparison_table":
      return <ComparisonTable block={block} />;
    case "concept_map":
      return <ConceptMap block={block} />;
    case "progress":
      return <Progress block={block} />;
    case "recommendation_card":
      return <RecommendationCard block={block} />;
    case "metric_grid":
      return <MetricGrid block={block} />;
    case "bar_chart":
      return <BarChart block={block} />;
    case "image":
      return <ImageFigure block={block} />;
    case "fallback":
      return <FallbackView block={block} />;
    default:
      return <UnknownBlock />;
  }
}

const KNOWN_CHECKS = new Set(["structure", "grounding_pages", "citations"]);

/** What was and was not checked, so a learner is never told more than the system actually did. */
export function ResponseMeta({ meta }: { meta: UIMeta }) {
  const lines: string[] = [];
  if (meta.simulated) lines.push(t("meta.simulated"));
  const v = meta.verification;
  if (v && v.checks_run.length > 0) {
    const names = v.checks_run.map((c) => (KNOWN_CHECKS.has(c) ? t(`check.${c}` as MessageKey) : c));
    lines.push(
      v.passed
        ? t("meta.verified", { checks: names.join(", ") })
        : t("meta.verification_failed", { issues: v.issues.join(", ") }),
    );
  } else if (meta.grounding !== "not_applicable") {
    lines.push(t("meta.not_verified"));
  }
  const pages = [...new Set(meta.sources.map((s) => s.page).filter((p): p is number => typeof p === "number"))];
  if (pages.length > 0) lines.push(t("meta.sources", { pages: pages.sort((a, b) => a - b).join(", ") }));
  if (meta.grounding === "no_context") lines.push(t("meta.no_context"));
  const warnings = meta.warnings.filter((w) => hasCode("warn", w)).map((w) => translateCode(t, "warn", w));
  if (lines.length === 0 && warnings.length === 0) return null;
  return (
    <aside className="meta" aria-label={t("meta.warnings")}>
      <ul>
        {[...lines, ...warnings].map((line, i) => (
          <li key={i}>{line}</li>
        ))}
      </ul>
    </aside>
  );
}

export function UISpecRenderer({ ui, compact = false }: { ui: ParsedUI; compact?: boolean }) {
  return (
    <div className="spec">
      {ui.spec.blocks.map((block, i) => (
        <BlockView key={i} block={block} />
      ))}
      {ui.dropped > 0 && <UnknownBlock />}
      {!compact && <ResponseMeta meta={ui.spec.meta} />}
    </div>
  );
}
