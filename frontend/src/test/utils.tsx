import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { PreferencesProvider } from "../a11y/PreferencesContext";
import { DEFAULT_PREFERENCES, type Preferences } from "../a11y/preferences";
import { ActionsContext, type Actions } from "../api/ActionsContext";
import { parseTutorResponse, parseUI, type ParsedUI, type TutorResponse } from "../ui-schema/schema";

const fixtureModules = import.meta.glob("../ui-schema/__fixtures__/*.json", { eager: true, import: "default" });

/** Real backend responses (mock services), exported by backend/agentic/scripts/export_ui_fixtures.py. */
export const fixtures: Record<string, unknown> = Object.fromEntries(
  Object.entries(fixtureModules).map(([path, value]) => [path.split("/").pop()!.replace(".json", ""), value]),
);
export const responseFixtures = Object.entries(fixtures).filter(([name]) => name !== "ui-spec.schema");

export const fixtureUI = (name: string): ParsedUI => parseTutorResponse(fixtures[name]).ui;

export function makeActions(overrides: Partial<Actions> = {}): Actions {
  const empty: TutorResponse = parseTutorResponse({
    request_id: "r",
    workflow: "answer",
    status: "ok",
    ui: { schema_version: "1.0", blocks: [{ type: "text", text: "ok" }], meta: {} },
  });
  return {
    submitAnswer: vi.fn().mockResolvedValue(empty),
    reportOutcome: vi.fn().mockResolvedValue({ accepted: true }),
    loadAsset: vi.fn().mockResolvedValue("blob:image"),
    ...overrides,
  };
}

export function renderWith(
  ui: ReactElement,
  options: { actions?: Actions | null; preferences?: Partial<Preferences> } = {},
) {
  const actions = options.actions === undefined ? makeActions() : options.actions;
  const preferences = { ...DEFAULT_PREFERENCES, ...options.preferences };
  return {
    actions,
    ...render(
      <PreferencesProvider initial={preferences}>
        <ActionsContext.Provider value={actions}>{ui}</ActionsContext.Provider>
      </PreferencesProvider>,
    ),
  };
}

export const specOf = (blocks: unknown[], meta: unknown = {}): ParsedUI =>
  parseUI({ schema_version: "1.0", blocks, meta });
