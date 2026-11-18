import type { Citation } from "@/lib/api";

export function CitationList({
  citations,
  title = "Sources cited",
}: {
  citations: Record<string, Citation>;
  title?: string;
}) {
  const labels = Object.keys(citations);
  if (!labels.length) return null;
  return (
    <>
      <h3 className="subheading">{title}</h3>
      <ol className="citation-list">
        {labels.map((label) => {
          const c = citations[label];
          return (
            <li key={label} id={`cite-${label}`}>
              <strong>[{label}]</strong> {c.document}
              {c.page ? `, page ${c.page}` : ""}
              <small className="cell-sub">“{c.excerpt}”</small>
            </li>
          );
        })}
      </ol>
    </>
  );
}
