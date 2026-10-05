import { WarehouseIcon } from 'lucide-react'
import type { ReactNode } from 'react'
import { NavLink, useLocation } from 'react-router'

import { PAGES, type PagePath } from '@/components/layout/pages'
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
  useSidebar,
} from '@/components/ui/sidebar'

interface AppSidebarProps {
  badges: Partial<Record<PagePath, { count: number; label: string; className: string }>>
  footer: ReactNode // controls that apply to the whole app (simulation, model, approver)
}

// The left-hand navigation: app name, one link per page (with counts), shared controls below.
export function AppSidebar({ badges, footer }: AppSidebarProps) {
  const { pathname } = useLocation()
  const { isMobile, setOpenMobile } = useSidebar()

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <div className="flex items-center gap-2 px-1 py-1.5">
          <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground">
            <WarehouseIcon className="size-4" />
          </div>
          <div className="min-w-0 group-data-[collapsible=icon]:hidden">
            <p className="truncate text-sm font-semibold">Warehouse Ops Agent</p>
            <p className="truncate text-xs text-muted-foreground">Fishing tackle DC</p>
          </div>
        </div>
      </SidebarHeader>

      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>Operations</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {PAGES.map(({ path, title, icon: Icon }) => {
                const badge = badges[path]
                return (
                  <SidebarMenuItem key={path}>
                    <SidebarMenuButton asChild isActive={pathname.startsWith(path)} tooltip={title}>
                      {/* On phones the sidebar is a drawer: close it once a page is picked. */}
                      <NavLink to={path} onClick={() => isMobile && setOpenMobile(false)}>
                        <Icon />
                        <span>{title}</span>
                      </NavLink>
                    </SidebarMenuButton>
                    {badge && badge.count > 0 && (
                      <SidebarMenuBadge aria-label={badge.label}>
                        <span className={badge.className}>{badge.count}</span>
                      </SidebarMenuBadge>
                    )}
                  </SidebarMenuItem>
                )
              })}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter className="group-data-[collapsible=icon]:hidden">{footer}</SidebarFooter>
      <SidebarRail />
    </Sidebar>
  )
}
