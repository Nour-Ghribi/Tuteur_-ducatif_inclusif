import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { PreferencesPanel } from "../a11y/PreferencesPanel";
import { sanitizePreferences } from "../a11y/preferences";
import { UISpecRenderer } from "../renderer/UISpecRenderer";
import { parseTutorResponse } from "../ui-schema/schema";
import { translateCode, t } from "../i18n";
import { fixtureUI, makeActions, renderWith, specOf } from "./utils";

describe("flashcards", () => {
  const deck = specOf([
    {
      type: "flashcard_deck",
      title: "Pigments",
      cards: [
        { front: "Q1", back: "A1" },
        { front: "Q2", back: "A2" },
      ],
    },
  ]);

  it("flips with the keyboard and moves with the arrow keys", async () => {
    const user = userEvent.setup();
    renderWith(<UISpecRenderer ui={deck} />);
    const card = screen.getByRole("button", { name: /Q1/ });
    expect(card).toHaveAttribute("aria-pressed", "false");
    card.focus();
    await user.keyboard("{Enter}");
    expect(screen.getByRole("button", { name: /A1/ })).toHaveAttribute("aria-pressed", "true");
    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("button", { name: /Q2/ })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByText("Carte 2 sur 2")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Suivant" })).toBeDisabled();
    await user.keyboard("{ArrowLeft}");
    expect(screen.getByText("Carte 1 sur 2")).toBeInTheDocument();
  });
});

describe("quiz", () => {
  const quiz = specOf([
    {
      type: "quiz",
      title: "Quiz",
      questions: [
        {
          question_id: "q1",
          item_type: "mcq",
          prompt: "Quel pigment ?",
          options: [
            { option_id: "a", text: "Chlorophylle" },
            { option_id: "b", text: "Glucose" },
          ],
        },
        { question_id: "q2", item_type: "short_answer", prompt: "Que rejette la plante ?", options: [] },
      ],
    },
  ]);

  it("sends the chosen option and shows the backend feedback in a live region", async () => {
    const user = userEvent.setup();
    const feedback = parseTutorResponse({
      request_id: "r",
      workflow: "answer",
      status: "ok",
      ui: {
        schema_version: "1.0",
        blocks: [{ type: "quiz_feedback", question_id: "q1", is_correct: false, score: 0, observed_errors: ["Erreur X"] }],
        meta: {},
      },
    });
    const actions = makeActions({ submitAnswer: vi.fn().mockResolvedValue(feedback) });
    renderWith(<UISpecRenderer ui={quiz} />, { actions });

    const [validate] = screen.getAllByRole("button", { name: "Valider" });
    expect(validate).toBeDisabled(); // nothing chosen yet
    await user.click(screen.getByRole("radio", { name: "Glucose" }));
    await user.click(validate);

    expect(actions.submitAnswer).toHaveBeenCalledWith("q1", { selected_option_id: "b" });
    const region = (await screen.findByText(/Ce n'est pas la bonne réponse/)).closest("[role=status]")!;
    expect(region).toHaveAttribute("aria-live", "polite");
    expect(within(region as HTMLElement).getByText("Erreur X")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Chlorophylle" })).toBeDisabled(); // single attempt
  });

  it("sends free text for open questions", async () => {
    const user = userEvent.setup();
    const actions = makeActions();
    renderWith(<UISpecRenderer ui={quiz} />, { actions });
    await user.type(screen.getByLabelText("Ta réponse"), "du dioxygène");
    await user.click(screen.getAllByRole("button", { name: "Valider" })[1]);
    expect(actions.submitAnswer).toHaveBeenCalledWith("q2", { text: "du dioxygène" });
  });

  it("shows a message and allows a retry when the request fails", async () => {
    const user = userEvent.setup();
    const actions = makeActions({ submitAnswer: vi.fn().mockRejectedValue(new Error("down")) });
    renderWith(<UISpecRenderer ui={quiz} />, { actions });
    await user.click(screen.getByRole("radio", { name: "Chlorophylle" }));
    await user.click(screen.getAllByRole("button", { name: "Valider" })[0]);
    expect(await screen.findByText("La demande n'a pas pu aboutir.")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Chlorophylle" })).toBeEnabled();
  });

  it("cannot submit without an application to submit to", () => {
    renderWith(<UISpecRenderer ui={quiz} />, { actions: null });
    expect(screen.getAllByRole("button", { name: "Valider" })[0]).toBeDisabled();
  });

  it("nests the remedial exercise returned after a wrong answer", () => {
    renderWith(<UISpecRenderer ui={fixtureUI("remediation")} />);
    expect(screen.getByText(/Hypothèse \(pas une certitude\)/)).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Valider" }).length).toBeGreaterThan(0);
  });
});

describe("steps, map, chart and recommendation", () => {
  it("walks through steps one at a time", async () => {
    const user = userEvent.setup();
    renderWith(<UISpecRenderer ui={fixtureUI("steps")} />);
    expect(screen.getByText(/Étape 1 sur/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Suivant" }));
    expect(screen.getByText(/Étape 2 sur/)).toBeInTheDocument();
    expect(document.querySelector("[aria-current=step]")).toBeInTheDocument();
  });

  it("draws the concept map with a text alternative, and only the text when visuals are reduced", () => {
    const ui = fixtureUI("concept_map");
    const full = renderWith(<UISpecRenderer ui={ui} />);
    expect(full.container.querySelector("svg[role=img]")).toBeInTheDocument();
    expect(full.container.querySelector("li")).toBeInTheDocument(); // relations are always listed
    full.unmount();
    const reduced = renderWith(<UISpecRenderer ui={ui} />, { preferences: { reduced_visual_complexity: true } });
    expect(reduced.container.querySelector("svg")).toBeNull();
    expect(reduced.container.querySelector("details")).toHaveAttribute("open");
  });

  it("gives every bar chart a data table", () => {
    const { container } = renderWith(<UISpecRenderer ui={fixtureUI("teacher_report")} />);
    const table = container.querySelector("table")!;
    expect(table.querySelectorAll("tbody tr").length).toBeGreaterThan(0);
    expect(table.querySelector("caption")).toHaveTextContent("Taux de réussite par notion");
  });

  it("reports the outcome of a recommended activity", async () => {
    const user = userEvent.setup();
    const actions = makeActions();
    renderWith(<UISpecRenderer ui={fixtureUI("recommendation")} />, { actions });
    await user.click(screen.getByRole("button", { name: "J'ai terminé cette activité" }));
    expect(actions.reportOutcome).toHaveBeenCalledWith(expect.stringMatching(/^rec-/), { completed: true });
    expect(await screen.findByText("Merci, ton retour est enregistré.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Je passe" })).toBeDisabled();
  });
});

describe("images", () => {
  const image = (extra = {}) => specOf([{ type: "image", asset_id: "img-1", alt_text: "Schéma de la feuille", ...extra }]);

  it("loads through the authenticated action and exposes the alt text", async () => {
    const actions = makeActions();
    renderWith(<UISpecRenderer ui={image({ adapted: true, long_description: "Longue description" })} />, { actions });
    expect(await screen.findByAltText("Schéma de la feuille")).toHaveAttribute("src", "blob:image");
    expect(actions.loadAsset).toHaveBeenCalledWith("img-1");
    expect(screen.getByText("Couleurs adaptées")).toBeInTheDocument();
    expect(screen.getByText("Longue description")).toBeInTheDocument();
  });

  it("reports a load failure in text", async () => {
    const actions = makeActions({ loadAsset: vi.fn().mockRejectedValue(new Error("403")) });
    renderWith(<UISpecRenderer ui={image()} />, { actions });
    expect(await screen.findByText("L'image n'a pas pu être chargée.")).toBeInTheDocument();
  });
});

describe("preferences", () => {
  it("sanitizes anything found in storage", () => {
    expect(sanitizePreferences(null).text_scale).toBe(1);
    const dirty = sanitizePreferences({ high_contrast: "yes", text_scale: 50, color_vision: "x", short_segments: true });
    expect(dirty).toMatchObject({ high_contrast: false, text_scale: 2, color_vision: "none", short_segments: true });
  });

  it("are explicit toggles, labelled, and never pre-selected", async () => {
    const user = userEvent.setup();
    renderWith(<PreferencesPanel />);
    const toggles = screen.getAllByRole("checkbox");
    expect(toggles).toHaveLength(5);
    toggles.forEach((box) => expect(box).not.toBeChecked());
    expect(screen.getByLabelText("Vision des couleurs")).toHaveValue("none");
    await user.click(screen.getByRole("checkbox", { name: "Contraste élevé" }));
    expect(screen.getByRole("checkbox", { name: "Contraste élevé" })).toBeChecked();
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-high-contrast"));
  });
});

describe("i18n", () => {
  it("never leaks an unknown code as an error", () => {
    expect(translateCode(t, "reason", "something_new")).toBe(t("reason.internal_error"));
    expect(translateCode(t, "msg", "something_new")).toBe("something new");
  });
});
