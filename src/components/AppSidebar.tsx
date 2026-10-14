import { Bot, MapPin, Users, GraduationCap, Settings, Info } from "lucide-react";
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar";

interface AppSidebarProps {
  onCampusMapToggle?: () => void;
}

const quickActions = [
  { title: "Campus Map", icon: MapPin },
  {
    title: "Faculty Info",
    icon: Users,
    href: "https://vjti.ac.in/electrical-engineering/",
  },
  {
    title: "Placements",
    icon: GraduationCap,
    href: "https://vjti.ac.in/training-and-placement-office/",
  },
];

const settingsItems = [
  { title: "About", icon: Info },
  { title: "Settings", icon: Settings },
];

export function AppSidebar({ onCampusMapToggle }: AppSidebarProps) {
  const { state } = useSidebar();
  const isCollapsed = state === "collapsed";

  return (
    <Sidebar
      collapsible="icon"
      className={isCollapsed ? "w-16" : "w-64"}
    >
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel className="flex items-center gap-2 px-4 py-4">
            <Bot className="h-5 w-5" />
            {!isCollapsed && <span className="font-semibold">Smart Campus</span>}
          </SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {quickActions.map((item) => (
                <SidebarMenuItem key={item.title}>
                  {item.title === "Placements" && item.href ? (
                    <SidebarMenuButton asChild className="hover:bg-accent/10">
                      <a href={item.href} target="_blank" rel="noopener noreferrer">
                        <item.icon className="h-4 w-4" />
                        {!isCollapsed && <span>{item.title}</span>}
                      </a>
                    </SidebarMenuButton>
                  ) : (
                    <SidebarMenuButton
                      className="hover:bg-accent/10"
                      onClick={() => {
                        if (item.title === "Campus Map" && onCampusMapToggle) {
                          onCampusMapToggle();
                        } else if (item.href) {
                          window.location.href = item.href;
                        }
                      }}
                    >
                      <item.icon className="h-4 w-4" />
                      {!isCollapsed && <span>{item.title}</span>}
                    </SidebarMenuButton>
                  )}
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        <SidebarGroup className="mt-auto">
          <SidebarGroupContent>
            <SidebarMenu>
              {settingsItems.map((item) => (
                <SidebarMenuItem key={item.title}>
                  <SidebarMenuButton className="hover:bg-accent/10">
                    <item.icon className="h-4 w-4" />
                    {!isCollapsed && <span>{item.title}</span>}
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
    </Sidebar>
  );
}
