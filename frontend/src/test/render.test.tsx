import axe from "axe-core";
import { describe, expect, it } from "vitest";
import { UISpecRenderer } from "../renderer/UISpecRenderer";
import { parseTutorResponse } from "../ui-schema/schema";
import { renderWith, responseFixtures, specOf } from "./utils";

/** jsdom has no layout engine, so colour contrast cannot be computed; it is covered by design (see styles.css). */
const AXE_OPTIONS = { rules: { "color-contrast": { enabled: false }, region: { enabled: false } } };

async function violations(container: HTMLElement) {
  const results = await axe.run(container, AXE_OPTIONS);
  return results.violations.map((v) => `${v.id}: ${v.help} (${v.nodes.map((n) => n.target).join(" | ")})`);
}

describe("every real backend response renders accessibly", () => {
  it.each(responseFixtures)("%s", async (_name, raw) => {
    const { container } = renderWith(<UISpecRenderer ui={parseTutorResponse(raw).ui} />);
    expect(container.textContent!.trim().length).toBeGreaterThan(0);
    expect(await violations(container)).toEqual([]);
  });

  it.each(responseFixtures)("%s with every accessibility preference enabled", async (_name, raw) => {
    const { container } = renderWith(<UISpecRenderer ui={parseTutorResponse(raw).ui} />, {
      preferences: {
        simplified_language: true,
        short_segments: true,
        reduced_visual_complexity: true,
        screen_reader_optimized: true,
        high_contrast: true,
        color_vision: "deuteranopia",
        text_scale: 2,
      },
    });
    expect(await violations(container)).toEqual([]);
  });

  it.each(responseFixtures)("%s shows no raw backend code to the user", (_name, raw) => {
    const { container } = renderWith(<UISpecRenderer ui={parseTutorResponse(raw).ui} />);
    // Codes are snake_case identifiers (generation_unavailable, no_progress_yet, ...).
    expect(container.textContent).not.toMatch(/\b[a-z]+_[a-z_]+\b/);
  });
});

describe("what the interface says about the response", () => {
  const meta = (fixture: string) => {
    const { container } = renderWith(<UISpecRenderer ui={parseTutorResponse(responseFixtures.find(([n]) => n === fixture)![1]).ui} />);
    return container.querySelector(".meta")?.textContent ?? "";
  };

  it("labels simulated data and lists the checks that actually ran", () => {
    const text = meta("quiz");
    expect(text).toContain("Données simulées");
    expect(text).toContain("format du contenu, pages sources");
    expect(text).toContain("1, 2");
  });

  it("only names the checks that ran: a report has no page-grounding check", () => {
    const text = meta("teacher_report");
    expect(text).toContain("Données simulées");
    expect(text).toContain("Vérifications effectuées : format du contenu");
    expect(text).not.toContain("pages sources");
  });

  it("states when a course figure has no description instead of inventing one", () => {
    const { container } = renderWith(
      <UISpecRenderer ui={specOf([{ type: "image", asset_id: "img-1", description_source: "placeholder" }])} />,
    );
    expect(container.textContent).toContain("La description de cette figure n'est pas disponible");
    expect(container.querySelector("figure")).toBeInTheDocument();
  });
});

describe("unsafe or malformed payloads", () => {
  it("renders markup in model text as inert text", () => {
    const hostile = `<img src=x onerror="alert(1)"><script>alert(2)</script>`;
    const { container } = renderWith(
      <UISpecRenderer
        ui={specOf([
          { type: "text", text: hostile },
          { type: "heading", text: hostile, level: 1 },
          { type: "bullet_list", items: [hostile] },
          { type: "callout", tone: "info", text: hostile },
        ])}
      />,
    );
    expect(container.querySelector("img, script")).toBeNull();
    expect(container.textContent).toContain(hostile);
  });

  it("drops unknown component types and tells the user", () => {
    const ui = specOf([
      { type: "text", text: "safe" },
      { type: "iframe", src: "https://evil.example" },
      { type: "html", markup: "<b>x</b>" },
    ]);
    expect(ui.dropped).toBe(2);
    const { container } = renderWith(<UISpecRenderer ui={ui} />);
    expect(container.querySelector("iframe")).toBeNull();
    expect(container.textContent).toContain("safe");
    expect(container.textContent).toContain("Une partie du contenu n'a pas pu être affichée");
  });

  it("drops a block that breaks its schema but keeps the others", () => {
    const ui = specOf([
      { type: "quiz", title: "t", questions: [] },
      { type: "text", text: "kept" },
    ]);
    expect(ui.dropped).toBe(1);
    expect(ui.spec.blocks).toHaveLength(1);
  });

  it.each([
    ["a non-object", "<html>"],
    ["null", null],
    ["a wrong schema version", { schema_version: "9.9", blocks: [{ type: "text", text: "x" }] }],
    ["no blocks array", { schema_version: "1.0" }],
    ["only invalid blocks", { schema_version: "1.0", blocks: [{ type: "nope" }] }],
  ])("falls back safely on %s", (_label, raw) => {
    const response = parseTutorResponse({ request_id: "r", workflow: "x", status: "ok", ui: raw });
    expect(response.ui.spec.blocks).toEqual([{ type: "fallback", reason_code: "ui_validation_failed" }]);
    const { container } = renderWith(<UISpecRenderer ui={response.ui} />);
    expect(container.textContent).toContain("n'a pas pu être affiché de façon sûre");
  });

  it("treats a malformed envelope as a failed response, never an exception", () => {
    expect(parseTutorResponse("garbage").status).toBe("failed");
    expect(parseTutorResponse({ status: "weird" }).ui.spec.blocks[0].type).toBe("fallback");
  });

  it("caps the number of rendered blocks", () => {
    const many = Array.from({ length: 100 }, () => ({ type: "text", text: "x" }));
    expect(specOf(many).spec.blocks.length).toBeLessThanOrEqual(40);
  });
});
