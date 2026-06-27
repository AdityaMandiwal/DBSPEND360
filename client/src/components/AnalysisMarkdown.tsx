import ReactMarkdown from 'react-markdown';

// Safe renderer for LLM-generated analysis text (plan §0.2). react-markdown
// does NOT render raw HTML unless `rehype-raw` is added (we deliberately do
// not), so this replaces the previous regex + dangerouslySetInnerHTML chains
// and removes the XSS surface while still rendering the **bold** / ## / ###
// the model emits.
export function AnalysisMarkdown({ children }: { children: string }) {
  return (
    <div className="text-sm leading-relaxed prose prose-sm dark:prose-invert max-w-none">
      <ReactMarkdown>{children}</ReactMarkdown>
    </div>
  );
}
