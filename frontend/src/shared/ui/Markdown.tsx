import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import s from "./Markdown.module.css";

/** Safe markdown rendering (no raw HTML), GitHub-flavoured tables and task lists. */
export function Markdown({ children }: { children: string }) {
  return (
    <div className={s.md}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children: c }) => (
            <a href={href} target="_blank" rel="noreferrer noopener">
              {c}
            </a>
          ),
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
