import { translateCode, t } from "../i18n";
import type { BlockOf } from "../ui-schema/schema";

/** Plain-text blocks. Content is rendered as React text nodes: never as HTML. */
export function Heading({ block }: { block: BlockOf<"heading"> }) {
  const label = block.text ?? (block.text_code ? translateCode(t, "label", block.text_code) : "");
  // The page title is the only h1; block level 1..3 maps to h2..h4.
  const Tag = (["h2", "h3", "h4"] as const)[Math.min(Math.max(block.level, 1), 3) - 1];
  return <Tag>{label}</Tag>;
}

export function Text({ block }: { block: BlockOf<"text"> }) {
  return <p>{block.text}</p>;
}

export function BulletList({ block }: { block: BlockOf<"bullet_list"> }) {
  return (
    <ul>
      {block.items.map((item, i) => (
        <li key={i}>{item}</li>
      ))}
    </ul>
  );
}

const TONE_ICON = { info: "ℹ", success: "✓", warning: "⚠", error: "✕" } as const;

export function Callout({ block }: { block: BlockOf<"callout"> }) {
  const message = block.message_code ? translateCode(t, "msg", block.message_code) : null;
  return (
    <div className={`callout callout-${block.tone}`} role={block.tone === "error" ? "alert" : "note"}>
      <span aria-hidden="true" className="callout-icon">
        {TONE_ICON[block.tone]}
      </span>
      <div>
        {message && <p>{message}</p>}
        {block.text && (block.message_code ? <blockquote>{block.text}</blockquote> : <p>{block.text}</p>)}
      </div>
    </div>
  );
}
