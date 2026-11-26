import { useId } from "react";
import { usePreferences } from "../a11y/PreferencesContext";
import { t } from "../i18n";
import type { BlockOf } from "../ui-schema/schema";

const W = 520;
const H = 380;
const short = (label: string, max = 20) => (label.length > max ? `${label.slice(0, max - 1)}…` : label);

/**
 * Radial concept map. The drawing is decorative: the full information is always available as a
 * list of relations (and it is the only rendering when reduced visual complexity is declared).
 */
export function ConceptMap({ block }: { block: BlockOf<"concept_map"> }) {
  const { preferences } = usePreferences();
  const titleId = useId();
  const descId = useId();
  const labels = new Map(block.nodes.map((n) => [n.node_id, n.label]));
  const others = block.nodes.filter((n) => n.node_id !== block.central_node_id);
  const position = new Map<string, { x: number; y: number }>([[block.central_node_id, { x: W / 2, y: H / 2 }]]);
  others.forEach((node, i) => {
    const angle = (2 * Math.PI * i) / Math.max(others.length, 1) - Math.PI / 2;
    position.set(node.node_id, { x: W / 2 + 190 * Math.cos(angle), y: H / 2 + 135 * Math.sin(angle) });
  });
  const relationText = (e: BlockOf<"concept_map">["edges"][number]) =>
    e.label
      ? t("map.relation", { source: labels.get(e.source) ?? e.source, label: e.label, target: labels.get(e.target) ?? e.target })
      : t("map.relation.plain", { source: labels.get(e.source) ?? e.source, target: labels.get(e.target) ?? e.target });

  return (
    <section aria-labelledby={titleId}>
      <h3 id={titleId}>{block.title}</h3>
      {!preferences.reduced_visual_complexity && (
        <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-labelledby={`${titleId} ${descId}`} className="concept-map">
          <title>{block.title}</title>
          <desc id={descId}>{t("map.alt")}</desc>
          {block.edges.map((edge, i) => {
            const a = position.get(edge.source);
            const b = position.get(edge.target);
            return a && b ? <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y} className="edge" /> : null;
          })}
          {block.nodes.map((node) => {
            const p = position.get(node.node_id)!;
            const central = node.node_id === block.central_node_id;
            return (
              <g key={node.node_id} transform={`translate(${p.x - 62} ${p.y - 18})`} aria-hidden="true">
                <rect width="124" height="36" rx="8" className={central ? "node node-central" : "node"} />
                <text x="62" y="23" textAnchor="middle">
                  {short(node.label)}
                </text>
              </g>
            );
          })}
        </svg>
      )}
      <details open={preferences.reduced_visual_complexity || preferences.screen_reader_optimized}>
        <summary>{t("map.text_alt")}</summary>
        <ul>
          {block.edges.length > 0 ? (
            block.edges.map((edge, i) => <li key={i}>{relationText(edge)}</li>)
          ) : (
            block.nodes.map((n) => <li key={n.node_id}>{n.label}</li>)
          )}
        </ul>
      </details>
    </section>
  );
}
