import { describe, expect, it } from "vitest";
import { hasCode } from "../i18n";
import { BLOCK_TYPES, UIBlock, parseTutorResponse } from "../ui-schema/schema";
import { fixtures, responseFixtures } from "./utils";

describe("backend <-> frontend UI contract", () => {
  it("has exported fixtures for every workflow", () => {
    expect(responseFixtures.length).toBeGreaterThanOrEqual(14);
  });

  it("knows exactly the block types the backend can emit (JSON Schema)", () => {
    const schema = fixtures["ui-spec.schema"] as {
      properties: { blocks: { items: { discriminator: { mapping: Record<string, string> } } } };
    };
    const backend = Object.keys(schema.properties.blocks.items.discriminator.mapping).sort();
    expect([...BLOCK_TYPES].sort()).toEqual(backend);
  });

  it.each(responseFixtures)("parses real response %s without dropping blocks", (_name, raw) => {
    const response = parseTutorResponse(raw);
    expect(response.ui.dropped).toBe(0);
    expect(response.ui.spec.blocks.length).toBeGreaterThan(0);
    for (const block of response.ui.spec.blocks) expect(UIBlock.safeParse(block).success).toBe(true);
  });

  it("covers the whole range of workflows and block types in the fixtures", () => {
    const seen = new Set<string>();
    for (const [, raw] of responseFixtures) {
      for (const block of parseTutorResponse(raw).ui.spec.blocks) seen.add(block.type);
    }
    expect([...BLOCK_TYPES].filter((type) => !seen.has(type))).toEqual([]);
  });

  it("translates every code the backend actually emitted", () => {
    const missing: string[] = [];
    const walk = (value: unknown) => {
      if (Array.isArray(value)) value.forEach(walk);
      else if (value && typeof value === "object") {
        for (const [key, v] of Object.entries(value)) {
          if (typeof v === "string") {
            if (key === "reason_code" && !hasCode("reason", v)) missing.push(`reason.${v}`);
            if (key === "message_code" && !hasCode("msg", v)) missing.push(`msg.${v}`);
            if (["label_code", "title_code", "text_code"].includes(key) && !hasCode("label", v))
              missing.push(`label.${v}`);
          } else if (key === "warnings" && Array.isArray(v)) {
            for (const w of v) if (typeof w === "string" && !hasCode("warn", w)) missing.push(`warn.${w}`);
          } else walk(v);
        }
      }
    };
    for (const [, raw] of responseFixtures) walk(raw);
    expect(missing).toEqual([]);
  });

  it("never receives an answer key in a served quiz (only in feedback after answering)", () => {
    const quizBlocks = responseFixtures
      .flatMap(([, raw]) => parseTutorResponse(raw).ui.spec.blocks)
      .filter((block) => block.type === "quiz");
    expect(quizBlocks.length).toBeGreaterThan(0);
    const text = JSON.stringify(quizBlocks);
    expect(text).not.toContain("correct_option_id");
    expect(text).not.toContain("reference_answer");
    expect(text).not.toContain("explanation");
  });
});
