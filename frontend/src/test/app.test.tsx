import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { tokenStore } from "../api/client";
import { fixtures } from "./utils";

const json = (body: unknown, status = 200) =>
  Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));

describe("application shell", () => {
  const fetchMock = vi.fn();
  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
    window.sessionStorage.clear();
    window.localStorage.clear();
    tokenStore.set("dev-token-for-tests");
  });
  afterEach(() => {
    fetchMock.mockReset();
    vi.unstubAllGlobals();
  });

  it("has one h1, a skip link, labelled landmarks and no axe violations", async () => {
    const { container } = render(<App />);
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(screen.getByRole("link", { name: "Aller au contenu principal" })).toHaveAttribute("href", "#main");
    expect(screen.getByRole("navigation", { name: "Navigation principale" })).toBeInTheDocument();
    const results = await axe.run(container, { rules: { "color-contrast": { enabled: false }, region: { enabled: false } } });
    expect(results.violations.map((v) => v.id)).toEqual([]);
  });

  it("sends the request with the token and the user's explicit preferences, then shows the result", async () => {
    const user = userEvent.setup();
    fetchMock.mockImplementation(() => json(fixtures.flashcards));
    render(<App />);

    await user.click(screen.getByRole("checkbox", { name: "Textes plus courts" }));
    await user.selectOptions(screen.getByLabelText("Vision des couleurs"), "protanopia");
    await user.type(screen.getByLabelText("Que veux-tu faire ?"), "Fais-moi des flashcards");
    await user.click(screen.getByRole("button", { name: "Envoyer" }));

    await screen.findByRole("heading", { name: "Résultat" });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/tutor/experiences");
    expect(init.headers.Authorization).toBe("Bearer dev-token-for-tests");
    const body = JSON.parse(init.body);
    expect(body).toMatchObject({ message: "Fais-moi des flashcards", course_id: "demo-bio-101" });
    expect(body.preferences).toMatchObject({ short_segments: true, color_vision: "protanopia", high_contrast: false });
    expect(body).not.toHaveProperty("student_ref");
    expect(await screen.findByRole("button", { name: /Question/ })).toBeInTheDocument();
    expect(screen.getByText(/Données simulées/)).toBeInTheDocument();
  });

  it.each([
    [401, "Jeton manquant ou invalide."],
    [403, "Tu n'as pas accès à cette action."],
    [504, "Le traitement a pris trop de temps. Réessaie."],
  ])("explains a %s in plain language", async (status, message) => {
    const user = userEvent.setup();
    fetchMock.mockImplementation(() => json({ error: { code: "x", message: "m", request_id: "r" } }, status));
    render(<App />);
    await user.type(screen.getByLabelText("Que veux-tu faire ?"), "Explique");
    await user.click(screen.getByRole("button", { name: "Envoyer" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(message);
  });

  it("explains an unreachable server", async () => {
    const user = userEvent.setup();
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    render(<App />);
    await user.type(screen.getByLabelText("Que veux-tu faire ?"), "Explique");
    await user.click(screen.getByRole("button", { name: "Envoyer" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Le serveur est injoignable");
  });

  it("shows a safe fallback when the server sends garbage", async () => {
    const user = userEvent.setup();
    fetchMock.mockImplementation(() => json({ request_id: "r", workflow: "experience", status: "ok", ui: { blocks: "x" } }));
    render(<App />);
    await user.type(screen.getByLabelText("Que veux-tu faire ?"), "Explique");
    await user.click(screen.getByRole("button", { name: "Envoyer" }));
    expect(await screen.findByText(/n'a pas pu être affiché de façon sûre/)).toBeInTheDocument();
  });

  it("requests the teacher report with only a class and a period", async () => {
    const user = userEvent.setup();
    fetchMock.mockImplementation(() => json(fixtures.teacher_report));
    render(<App />);
    await user.click(screen.getByRole("button", { name: "Enseignant" }));
    await user.click(screen.getByRole("button", { name: "Générer le rapport" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/teacher/reports");
    expect(Object.keys(JSON.parse(init.body)).sort()).toEqual(["class_id", "period_end", "period_start"]);
    expect(await screen.findByRole("table")).toBeInTheDocument();
  });

  it("keeps the development token in session storage only", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByText("Connexion de développement"));
    await user.clear(screen.getByLabelText("Jeton de développement"));
    await user.type(screen.getByLabelText("Jeton de développement"), "new-token");
    await user.click(screen.getByRole("button", { name: "Enregistrer le jeton" }));
    expect(window.sessionStorage.getItem("tutor.dev-token")).toBe("new-token");
    expect(JSON.stringify({ ...window.localStorage })).not.toContain("new-token");
  });
});
