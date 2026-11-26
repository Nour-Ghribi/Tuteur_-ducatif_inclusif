import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { DEFAULT_PREFERENCES, loadPreferences, savePreferences, type Preferences } from "./preferences";

interface PreferencesValue {
  preferences: Preferences;
  setPreferences: (next: Preferences) => void;
}

const PreferencesContext = createContext<PreferencesValue>({
  preferences: DEFAULT_PREFERENCES,
  setPreferences: () => undefined,
});

export function PreferencesProvider({
  children,
  initial,
}: {
  children: ReactNode;
  initial?: Preferences;
}) {
  const [preferences, setPreferences] = useState<Preferences>(() => initial ?? loadPreferences());

  useEffect(() => {
    const root = document.documentElement;
    root.style.setProperty("--text-scale", String(preferences.text_scale));
    root.toggleAttribute("data-high-contrast", preferences.high_contrast);
    root.toggleAttribute("data-reduced", preferences.reduced_visual_complexity);
    if (!initial) savePreferences(preferences);
  }, [preferences, initial]);

  const value = useMemo(() => ({ preferences, setPreferences }), [preferences]);
  return <PreferencesContext.Provider value={value}>{children}</PreferencesContext.Provider>;
}

export const usePreferences = () => useContext(PreferencesContext);
