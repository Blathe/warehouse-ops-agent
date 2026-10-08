import { ClipboardCheckIcon, LayoutDashboardIcon, ListTodoIcon, MapIcon } from 'lucide-react'

// Every page in the app. The order here is the order in the sidebar.
export const PAGES = [
  { path: '/overview', title: 'Overview', icon: LayoutDashboardIcon },
  { path: '/workspace', title: 'Workspace', icon: MapIcon },
  { path: '/tasks', title: 'Tasks', icon: ListTodoIcon },
  { path: '/counts', title: 'Cycle counts', icon: ClipboardCheckIcon },
] as const

export type PagePath = (typeof PAGES)[number]['path']
