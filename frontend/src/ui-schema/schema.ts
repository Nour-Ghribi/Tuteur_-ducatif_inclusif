/**
 * TypeScript mirror of the backend UI contract (backend/agentic/src/tutor_agentic/schemas/ui.py).
 *
 * The backend validates every spec before sending it; this schema validates it again on arrival, so
 * the renderer never receives a shape it does not know. A contract test compares BLOCK_TYPES with
 * the JSON Schema exported by the backend, and parses real backend responses (src/ui-schema/__fixtures__).
 * Text fields are plain text: nothing here is ever interpreted as HTML.
 */
import { z } from "zod";

const id = z.string().min(1).max(64);
const text = (max: number) => z.string().min(1).max(max);

export const HeadingBlock = z.object({
  type: z.literal("heading"),
  text: text(200).nullish(),
  text_code: id.nullish(),
  level: z.number().int().min(1).max(3).default(2),
});
export const TextBlock = z.object({ type: z.literal("text"), text: text(4000) });
export const BulletListBlock = z.object({
  type: z.literal("bullet_list"),
  items: z.array(text(500)).min(1).max(20),
});
export const CalloutBlock = z.object({
  type: z.literal("callout"),
  tone: z.enum(["info", "success", "warning", "error"]).default("info"),
  message_code: id.nullish(),
  text: text(1000).nullish(),
});
export const FlashcardDeckBlock = z.object({
  type: z.literal("flashcard_deck"),
  title: text(200),
  cards: z.array(z.object({ front: text(300), back: text(1000) })).min(1).max(30),
});
const QuizQuestion = z.object({
  question_id: id,
  item_type: z.enum(["mcq", "true_false", "short_answer"]),
  prompt: text(1000),
  options: z.array(z.object({ option_id: id, text: text(500) })).max(6).default([]),
});
export const QuizBlock = z.object({
  type: z.literal("quiz"),
  title: text(200),
  questions: z.array(QuizQuestion).min(1).max(20),
});
export const QuizFeedbackBlock = z.object({
  type: z.literal("quiz_feedback"),
  question_id: id,
  is_correct: z.boolean(),
  score: z.number().min(0).max(1),
  correct_option_id: id.nullish(),
  explanation: text(2000).nullish(),
  observed_errors: z.array(text(300)).max(10).default([]),
});
export const ConceptCardsBlock = z.object({
  type: z.literal("concept_cards"),
  title: text(200),
  concepts: z
    .array(z.object({ term: text(120), definition: text(1000), example: text(500).nullish() }))
    .min(1)
    .max(20),
});
export const StepsBlock = z.object({
  type: z.literal("steps"),
  title: text(200),
  steps: z.array(z.object({ title: text(200), detail: text(2000) })).min(1).max(15),
});
export const ComparisonTableBlock = z.object({
  type: z.literal("comparison_table"),
  title: text(200),
  columns: z.array(text(120)).min(2).max(5),
  rows: z.array(z.object({ criterion: text(120), values: z.array(text(500)).min(2).max(5) })).min(1).max(15),
});
export const ConceptMapBlock = z.object({
  type: z.literal("concept_map"),
  title: text(200),
  central_node_id: id,
  nodes: z.array(z.object({ node_id: id, label: text(120) })).min(2).max(40),
  edges: z
    .array(z.object({ source: id, target: id, label: text(80).nullish() }))
    .max(80)
    .default([]),
});
export const ProgressBlock = z.object({
  type: z.literal("progress"),
  label_code: id,
  value: z.number().min(0).max(1),
});
export const RecommendationCardBlock = z.object({
  type: z.literal("recommendation_card"),
  recommendation_id: id,
  activity_type: z.enum(["quiz", "exercise", "flashcards", "explanation", "revision", "mini_game"]),
  difficulty: z.enum(["easy", "medium", "hard"]),
  topic: text(200),
  rationale: text(500).nullish(),
  source: z.enum(["policy", "fallback"]).default("policy"),
});
export const MetricGridBlock = z.object({
  type: z.literal("metric_grid"),
  metrics: z
    .array(z.object({ label_code: id, value: z.number(), unit: z.enum(["count", "ratio", "seconds"]) }))
    .min(1)
    .max(12),
});
export const BarChartBlock = z.object({
  type: z.literal("bar_chart"),
  title_code: id,
  value_unit: z.enum(["ratio", "count"]),
  bars: z.array(z.object({ label: text(120), value: z.number().min(0) })).min(1).max(30),
});
export const ImageBlock = z.object({
  type: z.literal("image"),
  asset_id: id,
  alt_text: text(300).nullish(),
  long_description: text(2000).nullish(),
  adapted: z.boolean().default(false),
  description_source: z.enum(["model", "placeholder"]).default("model"),
});
export const FallbackBlock = z.object({
  type: z.literal("fallback"),
  reason_code: id,
  text: text(2000).nullish(),
});

export const UIBlock = z.discriminatedUnion("type", [
  HeadingBlock,
  TextBlock,
  BulletListBlock,
  CalloutBlock,
  FlashcardDeckBlock,
  QuizBlock,
  QuizFeedbackBlock,
  ConceptCardsBlock,
  StepsBlock,
  ComparisonTableBlock,
  ConceptMapBlock,
  ProgressBlock,
  RecommendationCardBlock,
  MetricGridBlock,
  BarChartBlock,
  ImageBlock,
  FallbackBlock,
]);
export type UIBlock = z.infer<typeof UIBlock>;
export type BlockOf<T extends UIBlock["type"]> = Extract<UIBlock, { type: T }>;

export const BLOCK_TYPES = UIBlock.options.map((o) => o.shape.type.value) as UIBlock["type"][];

export const VerificationReport = z.object({
  checks_run: z.array(z.string()).default([]),
  passed: z.boolean(),
  issues: z.array(z.string()).default([]),
  notes: z.array(z.string()).default([]),
});
export const UIMeta = z.object({
  language: z.string().nullish(),
  grounding: z.enum(["context_provided", "no_context", "not_applicable"]).default("not_applicable"),
  sources: z.array(z.object({ doc_id: z.string(), chunk_id: z.string(), page: z.number().nullish() })).default([]),
  verification: VerificationReport.nullish(),
  simulated: z.boolean().default(false),
  simulated_services: z.array(z.string()).default([]),
  fallback_used: z.boolean().default(false),
  warnings: z.array(z.string()).default([]),
  prompt_version: z.string().nullish(),
  model_id: z.string().nullish(),
});
export type UIMeta = z.infer<typeof UIMeta>;

export const SUPPORTED_SCHEMA_VERSION = "1.0";

export interface UISpec {
  blocks: UIBlock[];
  meta: UIMeta;
}

export const TutorResponseEnvelope = z.object({
  request_id: z.string(),
  workflow: z.string(),
  intent: z.string().nullish(),
  status: z.enum(["ok", "degraded", "failed"]),
  ui: z.unknown(),
});
export type TutorResponseEnvelope = z.infer<typeof TutorResponseEnvelope>;
export type TutorResponse = Omit<TutorResponseEnvelope, "ui"> & { ui: ParsedUI };

export interface ParsedUI {
  spec: UISpec;
  /** Blocks that were malformed or of an unknown type; shown as a safe placeholder, never rendered. */
  dropped: number;
}

const FALLBACK_SPEC = (reason: string): UISpec => ({
  blocks: [{ type: "fallback", reason_code: reason }],
  meta: UIMeta.parse({ fallback_used: true }),
});

/** Validates a payload from the backend. Never throws: anything unusable becomes a fallback block. */
export function parseUI(raw: unknown): ParsedUI {
  if (typeof raw !== "object" || raw === null) return { spec: FALLBACK_SPEC("ui_validation_failed"), dropped: 0 };
  const candidate = raw as { schema_version?: unknown; blocks?: unknown; meta?: unknown };
  if (candidate.schema_version !== SUPPORTED_SCHEMA_VERSION || !Array.isArray(candidate.blocks)) {
    return { spec: FALLBACK_SPEC("ui_validation_failed"), dropped: 0 };
  }
  const blocks: UIBlock[] = [];
  let dropped = 0;
  for (const block of candidate.blocks.slice(0, 40)) {
    const parsed = UIBlock.safeParse(block);
    if (parsed.success) blocks.push(parsed.data);
    else dropped += 1;
  }
  const meta = UIMeta.safeParse(candidate.meta ?? {});
  if (blocks.length === 0) return { spec: FALLBACK_SPEC("ui_validation_failed"), dropped };
  return { spec: { blocks, meta: meta.success ? meta.data : UIMeta.parse({}) }, dropped };
}

export function parseTutorResponse(raw: unknown): TutorResponse {
  const envelope = TutorResponseEnvelope.safeParse(raw);
  if (!envelope.success) {
    return {
      request_id: "unknown",
      workflow: "unknown",
      intent: null,
      status: "failed",
      ui: parseUI(null),
    };
  }
  return { ...envelope.data, ui: parseUI(envelope.data.ui) };
}
