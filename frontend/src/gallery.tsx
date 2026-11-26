/**
 * Component gallery (development only: served by `vite`, not part of the production build).
 * Renders real backend responses (mock services) exported to src/ui-schema/__fixtures__, so every
 * block can be reviewed visually without a backend. Preferences can be forced from the URL:
 *   /gallery.html?contrast=1&scale=1.5&reduced=1&color=deuteranopia&only=quiz,concept_map
 */
import { StrictMode, useMemo } from "react";
import { createRoot } from "react-dom/client";
import { PreferencesProvider } from "./a11y/PreferencesContext";
import { DEFAULT_PREFERENCES, sanitizePreferences } from "./a11y/preferences";
import { ActionsContext, type Actions } from "./api/ActionsContext";
import { UISpecRenderer } from "./renderer/UISpecRenderer";
import { parseTutorResponse } from "./ui-schema/schema";
import "./styles.css";

const modules = import.meta.glob("./ui-schema/__fixtures__/*.json", { eager: true, import: "default" });
const fixtures = Object.entries(modules)
  .map(([path, raw]) => [path.split("/").pop()!.replace(".json", ""), raw] as const)
  .filter(([name]) => name !== "ui-spec.schema");

const FIGURE =
  "data:image/svg+xml;utf8," +
  encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" width="420" height="180"><rect width="420" height="180" fill="#e8f0fe"/>` +
      `<circle cx="80" cy="90" r="50" fill="#c0392b"/><circle cx="210" cy="90" r="50" fill="#27ae60"/>` +
      `<circle cx="340" cy="90" r="50" fill="#2980b9"/></svg>`,
  );

function Gallery() {
  const params = new URLSearchParams(window.location.search);
  const only = params.get("only")?.split(",");
  const bare = params.get("bare") === "1"; // no gallery chrome: used for report figures
  const preferences = sanitizePreferences({
    ...DEFAULT_PREFERENCES,
    high_contrast: params.get("contrast") === "1",
    reduced_visual_complexity: params.get("reduced") === "1",
    text_scale: Number(params.get("scale") ?? 1),
    color_vision: params.get("color") ?? "none",
  });
  const actions = useMemo<Actions>(
    () => ({
      submitAnswer: () =>
        Promise.resolve(parseTutorResponse((modules["./ui-schema/__fixtures__/remediation.json"]))),
      reportOutcome: () => Promise.resolve({ accepted: true }),
      loadAsset: () => Promise.resolve(FIGURE),
    }),
    [],
  );
  return (
    <PreferencesProvider initial={preferences}>
      <ActionsContext.Provider value={actions}>
        <main>
          {!bare && <h1>Galerie des composants (données simulées)</h1>}
          {fixtures
            .filter(([name]) => !only || only.includes(name))
            .map(([name, raw]) => (
              <section key={name} aria-label={name} className={bare ? undefined : "panel"}>
                {!bare && <h2>{name}</h2>}
                <UISpecRenderer ui={parseTutorResponse(raw).ui} />
              </section>
            ))}
        </main>
      </ActionsContext.Provider>
    </PreferencesProvider>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Gallery />
  </StrictMode>,
);
