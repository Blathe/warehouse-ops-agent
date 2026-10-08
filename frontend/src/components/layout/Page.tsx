import type { ReactNode } from 'react'

// The scrolling area every admin page sits in. Pages mount fresh on each visit, so the fade-in
// plays every time you move between them.
export function Page({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-0 flex-1 animate-in overflow-y-auto fade-in-0 slide-in-from-bottom-1 p-4 duration-300 motion-reduce:animate-none">
      {children}
    </div>
  )
}
