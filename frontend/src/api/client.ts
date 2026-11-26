import type { Preferences } from "../a11y/preferences";
import { parseTutorResponse, type TutorResponse } from "../ui-schema/schema";

const BASE = "/api/v1";
const TOKEN_KEY = "tutor.dev-token";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

/** Development token kept for the browser session only (never persisted across sessions). */
export const tokenStore = {
  get(): string {
    try {
      return window.sessionStorage.getItem(TOKEN_KEY) ?? "";
    } catch {
      return "";
    }
  },
  set(token: string): void {
    try {
      window.sessionStorage.setItem(TOKEN_KEY, token);
    } catch {
      /* ignore: the token then lasts until the next reload */
    }
  },
};

async function call(path: string, init: RequestInit = {}): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      ...init,
      headers: {
        Accept: "application/json",
        ...(init.body ? { "Content-Type": "application/json" } : {}),
        Authorization: `Bearer ${tokenStore.get()}`,
      },
    });
  } catch {
    throw new ApiError(0, "network", "network");
  }
  if (!response.ok) {
    let code = "http_error";
    let message = response.statusText;
    try {
      const body = (await response.json()) as { error?: { code?: string; message?: string } };
      code = body.error?.code ?? code;
      message = body.error?.message ?? message;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(response.status, code, message);
  }
  return response;
}

const post = async (path: string, body: unknown): Promise<unknown> =>
  (await call(path, { method: "POST", body: JSON.stringify(body) })).json();

export interface ExperienceInput {
  message: string;
  course_id: string;
  topic?: string;
  requested_format?: string;
  preferences: Preferences;
}

export const api = {
  createExperience: async (input: ExperienceInput): Promise<TutorResponse> =>
    parseTutorResponse(
      await post("/tutor/experiences", {
        ...input,
        topic: input.topic || undefined,
        requested_format: input.requested_format || undefined,
      }),
    ),

  submitAnswer: async (
    questionId: string,
    answer: { selected_option_id?: string; text?: string },
    preferences: Preferences,
  ): Promise<TutorResponse> =>
    parseTutorResponse(
      await post("/tutor/answers", { question_id: questionId, answer, preferences }),
    ),

  progress: async (): Promise<TutorResponse> =>
    parseTutorResponse(await (await call("/tutor/progress")).json()),

  reportOutcome: async (
    recommendationId: string,
    outcome: { completed: boolean; score?: number },
  ): Promise<{ accepted: boolean }> =>
    (await post(
      `/tutor/recommendations/${encodeURIComponent(recommendationId)}/outcome`,
      outcome,
    )) as { accepted: boolean },

  teacherReport: async (input: {
    class_id: string;
    period_start: string;
    period_end: string;
  }): Promise<TutorResponse> => parseTutorResponse(await post("/teacher/reports", input)),

  /** Images need the bearer token, so they are fetched and exposed as object URLs. */
  assetUrl: async (assetId: string): Promise<string> =>
    URL.createObjectURL(await (await call(`/assets/${encodeURIComponent(assetId)}`)).blob()),
};
