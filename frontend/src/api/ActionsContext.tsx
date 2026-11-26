import { createContext, useContext } from "react";
import type { TutorResponse } from "../ui-schema/schema";

/**
 * What interactive blocks can ask the application to do. Blocks never call the network themselves:
 * tests (and any other host) supply their own implementation.
 */
export interface Actions {
  submitAnswer(
    questionId: string,
    answer: { selected_option_id?: string; text?: string },
  ): Promise<TutorResponse>;
  reportOutcome(recommendationId: string, outcome: { completed: boolean }): Promise<{ accepted: boolean }>;
  loadAsset(assetId: string): Promise<string>;
}

export const ActionsContext = createContext<Actions | null>(null);
export const useActions = (): Actions | null => useContext(ActionsContext);
