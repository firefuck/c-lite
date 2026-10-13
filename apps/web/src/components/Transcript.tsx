import type { TranscriptItem } from "@clite/shared";
import { useLayoutEffect, useRef } from "react";

/** Plain text with fenced code blocks shown as <pre>. Deliberately not a Markdown renderer:
 *  everything the model writes is text, never markup. */
export function RichText({ text }: { text: string }) {
  const parts = text.split(/```[^\n]*\n?/);
  return (
    <>
      {parts.map((part, index) =>
        !part ? null : index % 2 === 1 ? <pre key={index}>{part.replace(/\n$/, "")}</pre> : part,
      )}
    </>
  );
}

function toolLine(item: Extract<TranscriptItem, { kind: "tool" }>): string {
  const base = item.preview ? `${item.name}  ${item.preview}` : item.name;
  if (item.status === "running") return base;
  const duration = item.duration === null ? "" : `  (${item.duration.toFixed(1)}s)`;
  return `${item.status === "failed" ? "✗" : "✓"} ${base}${duration}`;
}

function Item({ item }: { item: TranscriptItem }) {
  switch (item.kind) {
    case "user":
    case "assistant":
      return (
        <div className={`message ${item.kind}`}>
          <RichText text={item.text} />
        </div>
      );
    case "reasoning":
      return <div className="reasoning">{item.text}</div>;
    case "tool":
      return (
        <div className={`tool${item.status === "running" ? " running" : item.status === "failed" ? " failed" : ""}`}>
          {toolLine(item)}
        </div>
      );
    case "notice":
      return <div className={`message ${item.level === "error" ? "error" : "notice"}`}>{item.text}</div>;
  }
}

/** The active conversation. It scrolls to the newest line whenever the transcript changes. */
export function Transcript({ items, banner }: { items: TranscriptItem[]; banner: string }) {
  const element = useRef<HTMLDivElement>(null);
  // biome-ignore lint/correctness/useExhaustiveDependencies: every new item scrolls the transcript to the bottom.
  useLayoutEffect(() => {
    const transcript = element.current;
    if (transcript) transcript.scrollTop = transcript.scrollHeight;
  }, [items]);
  return (
    <div id="transcript" aria-live="polite" ref={element}>
      <div className="transcript-body">
        {banner && !items.length ? <div className="message error">{banner}</div> : null}
        {items.map((item, index) => (
          <Item key={index} item={item} />
        ))}
      </div>
    </div>
  );
}
