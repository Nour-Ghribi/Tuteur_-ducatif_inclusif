import { useId, useState, type FormEvent, type KeyboardEvent } from "react";
import { useActions } from "../api/ActionsContext";
import { t, translateCode } from "../i18n";
import { UISpecRenderer } from "../renderer/UISpecRenderer";
import type { BlockOf, TutorResponse } from "../ui-schema/schema";

export function FlashcardDeck({ block }: { block: BlockOf<"flashcard_deck"> }) {
  const [index, setIndex] = useState(0);
  const [flipped, setFlipped] = useState(false);
  const titleId = useId();
  const hintId = useId();
  const card = block.cards[index];
  const go = (next: number) => {
    setIndex(Math.min(Math.max(next, 0), block.cards.length - 1));
    setFlipped(false);
  };
  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key === "ArrowRight") go(index + 1);
    if (e.key === "ArrowLeft") go(index - 1);
  };
  return (
    <section aria-labelledby={titleId} className="deck" onKeyDown={onKeyDown}>
      <h3 id={titleId}>{block.title}</h3>
      <p id={hintId} className="muted">
        {t("card.hint")}
      </p>
      <p className="muted">{t("card.n_of", { n: index + 1, total: block.cards.length })}</p>
      <button
        type="button"
        className="flashcard"
        aria-pressed={flipped}
        aria-describedby={hintId}
        onClick={() => setFlipped((f) => !f)}
      >
        <span className="face-label">{flipped ? t("common.answer") : t("common.question")}</span>
        <span className="face-text">{flipped ? card.back : card.front}</span>
        <span className="sr-only">{t("card.flip")}</span>
      </button>
      <div className="row">
        <button type="button" onClick={() => go(index - 1)} disabled={index === 0}>
          {t("nav.prev")}
        </button>
        <button type="button" onClick={() => go(index + 1)} disabled={index === block.cards.length - 1}>
          {t("nav.next")}
        </button>
      </div>
      <div className="sr-only" aria-live="polite">
        {flipped ? `${t("common.answer")} : ${card.back}` : `${t("common.question")} : ${card.front}`}
      </div>
    </section>
  );
}

type Question = BlockOf<"quiz">["questions"][number];
type Submission = { state: "idle" | "sending" | "done" | "error"; result?: TutorResponse };

function QuizQuestion({ question, index }: { question: Question; index: number }) {
  const actions = useActions();
  const [choice, setChoice] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [submission, setSubmission] = useState<Submission>({ state: "idle" });
  const inputId = useId();
  const open = question.item_type === "short_answer";
  const ready = open ? text.trim().length > 0 : choice !== null;
  const locked = submission.state === "sending" || submission.state === "done";

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!actions || !ready || locked) return;
    setSubmission({ state: "sending" });
    try {
      const result = await actions.submitAnswer(
        question.question_id,
        open ? { text: text.trim() } : { selected_option_id: choice ?? undefined },
      );
      setSubmission({ state: "done", result });
    } catch {
      setSubmission({ state: "error" });
    }
  }

  return (
    <form onSubmit={onSubmit} className="question">
      <fieldset disabled={locked}>
        <legend>
          {index + 1}. {question.prompt}
        </legend>
        {open ? (
          <label htmlFor={inputId} className="field">
            <span>{t("quiz.your_answer")}</span>
            <input id={inputId} type="text" value={text} onChange={(e) => setText(e.target.value)} />
          </label>
        ) : (
          question.options.map((option) => (
            <label key={option.option_id} className="check">
              <input
                type="radio"
                name={question.question_id}
                value={option.option_id}
                checked={choice === option.option_id}
                onChange={() => setChoice(option.option_id)}
              />
              <span>{option.text}</span>
            </label>
          ))
        )}
      </fieldset>
      <button type="submit" disabled={!actions || !ready || locked}>
        {submission.state === "sending" ? t("quiz.sending") : t("quiz.submit")}
      </button>
      <div role="status" aria-live="polite" className="feedback-region">
        {submission.state === "done" && submission.result && <UISpecRenderer ui={submission.result.ui} compact />}
        {submission.state === "error" && <p className="callout callout-error">{t("error.generic")}</p>}
      </div>
    </form>
  );
}

export function Quiz({ block }: { block: BlockOf<"quiz"> }) {
  const titleId = useId();
  return (
    <section aria-labelledby={titleId}>
      <h3 id={titleId}>{block.title}</h3>
      {block.questions.map((question, i) => (
        <QuizQuestion key={question.question_id} question={question} index={i} />
      ))}
    </section>
  );
}

export function QuizFeedback({ block }: { block: BlockOf<"quiz_feedback"> }) {
  return (
    <div className={`feedback ${block.is_correct ? "feedback-ok" : "feedback-ko"}`}>
      <p className="feedback-title">
        <span aria-hidden="true">{block.is_correct ? "✓ " : "✕ "}</span>
        {block.is_correct ? t("feedback.correct") : t("feedback.incorrect")}
        <span className="muted"> — {t("feedback.score", { score: Math.round(block.score * 100) })}</span>
      </p>
      {block.explanation && (
        <p>
          <strong>{t("feedback.explanation")} : </strong>
          {block.explanation}
        </p>
      )}
      {block.observed_errors.length > 0 && (
        <>
          <p>
            <strong>{t("feedback.observed")} :</strong>
          </p>
          <ul>
            {block.observed_errors.map((error, i) => (
              <li key={i}>{translateCode(t, "obs", error)}</li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

export function ConceptCards({ block }: { block: BlockOf<"concept_cards"> }) {
  const titleId = useId();
  return (
    <section aria-labelledby={titleId}>
      <h3 id={titleId}>{block.title}</h3>
      <ul className="cards">
        {block.concepts.map((concept, i) => (
          <li key={i}>
            <article className="card">
              <h4>{concept.term}</h4>
              <p>{concept.definition}</p>
              {concept.example && <p className="muted">{concept.example}</p>}
            </article>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function Steps({ block }: { block: BlockOf<"steps"> }) {
  const [current, setCurrent] = useState(0);
  const titleId = useId();
  const step = block.steps[current];
  return (
    <section aria-labelledby={titleId}>
      <h3 id={titleId}>{block.title}</h3>
      <ol className="step-list">
        {block.steps.map((s, i) => (
          <li key={i} aria-current={i === current ? "step" : undefined} className={i === current ? "current" : ""}>
            {s.title}
          </li>
        ))}
      </ol>
      <div className="card" aria-live="polite">
        <p className="muted">{t("step.n_of", { n: current + 1, total: block.steps.length })}</p>
        <h4>{step.title}</h4>
        <p>{step.detail}</p>
      </div>
      <div className="row">
        <button type="button" onClick={() => setCurrent((c) => c - 1)} disabled={current === 0}>
          {t("nav.prev")}
        </button>
        <button
          type="button"
          onClick={() => setCurrent((c) => c + 1)}
          disabled={current === block.steps.length - 1}
        >
          {t("nav.next")}
        </button>
      </div>
    </section>
  );
}

export function ComparisonTable({ block }: { block: BlockOf<"comparison_table"> }) {
  return (
    <div className="table-wrap" tabIndex={0} role="region" aria-label={block.title}>
      <table>
        <caption>{block.title}</caption>
        <thead>
          <tr>
            <th scope="col">{t("table.compare")}</th>
            {block.columns.map((column, i) => (
              <th key={i} scope="col">
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {block.rows.map((row, i) => (
            <tr key={i}>
              <th scope="row">{row.criterion}</th>
              {row.values.map((value, j) => (
                <td key={j}>{value}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
