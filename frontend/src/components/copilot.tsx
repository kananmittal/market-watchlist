"use client";

// Copilot panel. Deliberately not the first thing on the page: it explains the
// evidence, it is not the product. When it is unavailable the evidence cards
// still answer the question, and the UI says so plainly.

import { useState } from "react";
import { ApiError, api } from "@/lib/api";
import type { CopilotReply } from "@/lib/types";
import { Button, Card, SectionHeading } from "./ui";

/**
 * Minimal markdown rendering.
 *
 * The model is asked for plain prose, but instruction-following is not a
 * guarantee: stray `**bold**` was reaching the page as literal asterisks.
 * Handles bold and simple bullets, and nothing else - the copilot has no
 * business emitting arbitrary HTML.
 */
function renderInline(text: string, key: number) {
  const parts = text.split(/\*\*(.+?)\*\*/g);
  return (
    <span key={key}>
      {parts.map((part, i) =>
        i % 2 === 1 ? (
          <strong key={i} className="font-semibold text-ink">
            {part}
          </strong>
        ) : (
          part
        ),
      )}
    </span>
  );
}

function renderAnswer(answer: string) {
  const lines = answer.split("\n").filter((l) => l.trim().length > 0);
  return lines.map((line, i) => {
    const trimmed = line.trim();
    if (/^[-*\u2022]\s+/.test(trimmed)) {
      return (
        <div key={i} className="flex gap-2">
          <span className="text-faint" aria-hidden="true">
            &middot;
          </span>
          <span>{renderInline(trimmed.replace(/^[-*\u2022]\s+/, ""), i)}</span>
        </div>
      );
    }
    return <p key={i}>{renderInline(trimmed, i)}</p>;
  });
}

const SUGGESTIONS = [
  "What changed in my watchlist?",
  "Which stock deserves attention?",
  "Why is this highlighted?",
];

export function CopilotPanel({ symbol, compact = false }: { symbol?: string; compact?: boolean }) {
  const [question, setQuestion] = useState("");
  const [reply, setReply] = useState<CopilotReply | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function ask(q: string) {
    const text = q.trim();
    if (!text || busy) return;
    setBusy(true);
    setError(null);
    setReply(null);
    try {
      setReply(await api.copilot(text, symbol));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not reach the copilot.");
    } finally {
      setBusy(false);
    }
  }

  const suggestions = symbol
    ? [`Why is ${symbol} highlighted?`, `Explain ${symbol}`, `Is this unusual for ${symbol}?`]
    : SUGGESTIONS;

  return (
    <Card className={compact ? "p-4" : "p-5"}>
      <SectionHeading
        title="Ask about the evidence"
        hint={symbol ? symbol : "your watchlist"}
      />

      <form
        onSubmit={(e) => {
          e.preventDefault();
          ask(question);
        }}
        className="flex gap-2"
      >
        <label htmlFor="copilot-input" className="sr-only">
          Ask a question about your watchlist
        </label>
        <input
          id="copilot-input"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder={symbol ? `Ask about ${symbol}…` : "Ask about your watchlist…"}
          className="flex-1 rounded-md border border-line bg-surface px-3 py-2 text-[13px] text-ink placeholder:text-faint"
        />
        <Button type="submit" disabled={busy || !question.trim()} size="sm">
          {busy ? "Thinking…" : "Ask"}
        </Button>
      </form>

      <div className="mt-2 flex flex-wrap gap-1.5">
        {suggestions.map((s) => (
          <button
            key={s}
            onClick={() => {
              setQuestion(s);
              ask(s);
            }}
            disabled={busy}
            className="rounded-full border border-line px-2.5 py-1 text-[11px] text-muted hover:bg-surface-2 hover:text-ink disabled:opacity-50"
          >
            {s}
          </button>
        ))}
      </div>

      {error ? (
        <p role="alert" className="mt-3 rounded-md bg-down-soft px-3 py-2 text-[13px] text-down">
          {error}
        </p>
      ) : null}

      {reply ? (
        <div className="mt-4 border-t border-line pt-3">
          {!reply.grounded ? (
            <p className="mb-2 rounded-md bg-medium-soft px-2.5 py-1.5 text-[11px] text-medium">
              The AI explanation is unavailable, so the underlying evidence is shown instead.
            </p>
          ) : null}
          <div className="space-y-1.5 text-[13px] leading-relaxed text-ink-2">
            {renderAnswer(reply.answer)}
          </div>
          {reply.grounded && reply.evidence.length ? (
            <details className="mt-3">
              <summary className="cursor-pointer text-[11px] text-muted hover:text-ink">
                Evidence this answer was grounded in ({reply.evidence.length})
              </summary>
              <ul className="mt-2 space-y-1">
                {reply.evidence.map((e, i) => (
                  <li key={i} className="text-[12px] text-muted">
                    · {e}
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
          <p className="mt-3 text-[11px] text-faint">
            Answers are generated only from the evidence above. Not investment advice.
          </p>
        </div>
      ) : null}
    </Card>
  );
}
