import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { cn } from '@/lib/utils'

// How each markdown element looks inside a chat bubble. Tailwind has no built-in prose
// styling, so the elements are styled one by one. Colors come from the theme, so the
// bubble's own background and dark mode keep working.
const components: Components = {
  p: ({ node: _node, ...props }) => <p className="my-2" {...props} />,
  h1: ({ node: _node, ...props }) => <h3 className="mt-3 mb-1 text-base font-semibold" {...props} />,
  h2: ({ node: _node, ...props }) => <h3 className="mt-3 mb-1 text-base font-semibold" {...props} />,
  h3: ({ node: _node, ...props }) => <h4 className="mt-3 mb-1 font-semibold" {...props} />,
  h4: ({ node: _node, ...props }) => <h4 className="mt-3 mb-1 font-semibold" {...props} />,
  ul: ({ node: _node, ...props }) => <ul className="my-2 list-disc pl-5" {...props} />,
  ol: ({ node: _node, ...props }) => <ol className="my-2 list-decimal pl-5" {...props} />,
  li: ({ node: _node, ...props }) => <li className="my-0.5" {...props} />,
  a: ({ node: _node, ...props }) => (
    <a
      className="underline underline-offset-2"
      target="_blank"
      rel="noreferrer noopener"
      {...props}
    />
  ),
  hr: ({ node: _node, ...props }) => <hr className="my-3 border-foreground/15" {...props} />,
  blockquote: ({ node: _node, ...props }) => (
    <blockquote className="my-2 border-l-2 border-foreground/20 pl-3 text-muted-foreground" {...props} />
  ),
  // Block code is a <code> inside a <pre>; inline code is a bare <code>.
  pre: ({ node: _node, ...props }) => (
    <pre
      className="my-2 overflow-x-auto rounded-md bg-foreground/10 p-2 text-xs [&>code]:bg-transparent [&>code]:p-0"
      {...props}
    />
  ),
  code: ({ node: _node, ...props }) => (
    <code className="rounded bg-foreground/10 px-1 py-0.5 font-mono text-[0.85em]" {...props} />
  ),
  // Wide tables scroll sideways inside the bubble instead of stretching it.
  table: ({ node: _node, ...props }) => (
    <div className="my-2 overflow-x-auto">
      <table className="w-full border-collapse text-xs" {...props} />
    </div>
  ),
  th: ({ node: _node, ...props }) => (
    <th
      className="border-b border-foreground/25 px-2 py-1 text-left font-medium whitespace-nowrap"
      {...props}
    />
  ),
  td: ({ node: _node, ...props }) => (
    <td className="border-b border-foreground/10 px-2 py-1 align-top" {...props} />
  ),
}

// Renders an assistant reply. Raw HTML in the text is not rendered (react-markdown escapes
// it unless the rehype-raw plugin is added), and unsafe link targets like javascript: are
// dropped, so a reply can't inject markup into the page.
export function Markdown({ children, className }: { children: string; className?: string }) {
  return (
    <div className={cn('min-w-0 break-words [&>*:first-child]:mt-0 [&>*:last-child]:mb-0', className)}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {children}
      </ReactMarkdown>
    </div>
  )
}
