import { Fragment, type ReactNode } from "react";

// Minimal, safe markdown: headings, bullet and numbered lists, simple tables, paragraphs,
// **bold**, and [C3] citations. Builds React elements only (no innerHTML), so generated text
// cannot inject markup.
function inline(
  text: string,
  citations: Set<string>,
  key: string,
): ReactNode[] {
  const parts = text.split(/(\*\*[^*]+\*\*|\[[CW]\d{1,6}\])/g);
  return parts.map((part, i) => {
    const k = `${key}-${i}`;
    if (/^\*\*[^*]+\*\*$/.test(part))
      return <strong key={k}>{part.slice(2, -2)}</strong>;
    const cite = part.match(/^\[([CW]\d{1,6})\]$/);
    if (cite) {
      const label = cite[1];
      return citations.has(label) ? (
        <a key={k} className="cite" href={`#cite-${label}`}>
          {label}
        </a>
      ) : (
        <span key={k} className="cite cite-missing" title="Unknown source">
          {label}
        </span>
      );
    }
    return <Fragment key={k}>{part}</Fragment>;
  });
}

const cells = (line: string) =>
  line
    .trim()
    .replace(/^\||\|$/g, "")
    .split("|")
    .map((c) => c.trim());

export function Markdown({
  text,
  citations = [],
}: {
  text: string;
  citations?: string[];
}) {
  const known = new Set(citations);
  const blocks: ReactNode[] = [];
  let list: string[] = [];
  let ordered = false;
  let paragraph: string[] = [];
  let table: string[][] = [];
  const flush = () => {
    if (paragraph.length) {
      const key = `p${blocks.length}`;
      blocks.push(<p key={key}>{inline(paragraph.join(" "), known, key)}</p>);
      paragraph = [];
    }
    if (list.length) {
      const key = `l${blocks.length}`;
      const items = list.map((item, i) => (
        <li key={i}>{inline(item, known, `${key}-${i}`)}</li>
      ));
      blocks.push(
        ordered ? <ol key={key}>{items}</ol> : <ul key={key}>{items}</ul>,
      );
      list = [];
    }
    if (table.length) {
      const key = `t${blocks.length}`;
      const [head, ...rows] = table;
      blocks.push(
        <div className="table-wrap" key={key}>
          <table className="data-table">
            <thead>
              <tr>
                {head.map((c, i) => (
                  <th key={i} scope="col">
                    {inline(c, known, `${key}-h${i}`)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, r) => (
                <tr key={r}>
                  {row.map((c, i) => (
                    <td key={i}>{inline(c, known, `${key}-${r}-${i}`)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>,
      );
      table = [];
    }
  };
  for (const line of text.split("\n")) {
    const heading = line.match(/^(#{1,3})\s+(.*)$/);
    const bullet = line.match(/^\s*[-*]\s+(.*)$/);
    const numbered = line.match(/^\s*\d+\.\s+(.*)$/);
    if (/^\s*\|/.test(line)) {
      if (paragraph.length || list.length) flush();
      if (!/^\s*\|[\s\-:|]+\|\s*$/.test(line)) table.push(cells(line));
    } else if (heading) {
      flush();
      const key = `h${blocks.length}`;
      const content = inline(heading[2], known, key);
      const level = heading[1].length;
      blocks.push(
        level === 1 ? (
          <h2 key={key}>{content}</h2>
        ) : level === 2 ? (
          <h3 key={key}>{content}</h3>
        ) : (
          <h4 key={key}>{content}</h4>
        ),
      );
    } else if (bullet || numbered) {
      const isOrdered = !!numbered && !bullet;
      if (
        paragraph.length ||
        table.length ||
        (list.length && ordered !== isOrdered)
      )
        flush();
      ordered = isOrdered;
      list.push((bullet ?? numbered)![1]);
    } else if (!line.trim()) {
      flush();
    } else {
      if (list.length || table.length) flush();
      paragraph.push(line.trim());
    }
  }
  flush();
  return <div className="markdown">{blocks}</div>;
}
