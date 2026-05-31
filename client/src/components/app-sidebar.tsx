import { Video, AlertTriangle, Film, LogOut } from "lucide-react";
import { useLocation } from "wouter";
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

const menuItems = [
  {
    title: "Live Feed",
    url: "/dashboard/live",
    icon: Video,
  },
  {
    title: "Unusual Activity",
    url: "/dashboard/alerts",
    icon: AlertTriangle,
  },
  {
    title: "Recordings",
    url: "/dashboard/recordings",
    icon: Film,
  },
];

export function AppSidebar() {
  const [location, setLocation] = useLocation();
  const { isMobile, setOpenMobile } = useSidebar();

  const handleNavigation = (url: string) => {
    setLocation(url);
    if (isMobile) {
      setOpenMobile(false);
    }
  };

  const handleLogout = () => {
    // 🧹 Clear localStorage user data
    localStorage.removeItem("user");

    // 🔁 Redirect to login page
    setLocation("/login");

    if (isMobile) {
      setOpenMobile(false);
    }
  };


  return (
    <Sidebar>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>SecureVision</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {menuItems.map((item) => (
                <SidebarMenuItem key={item.title}>
                  <SidebarMenuButton
                    asChild
                    isActive={location === item.url}
                    data-testid={`link-${item.title.toLowerCase().replace(/\s+/g, '-')}`}
                  >
                    <a href={item.url} onClick={(e) => { e.preventDefault(); handleNavigation(item.url); }}>
                      <item.icon />
                      <span>{item.title}</span>
                    </a>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        <SidebarGroup className="mt-auto">
          <SidebarGroupContent>
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton onClick={handleLogout} data-testid="button-logout">
                  <LogOut />
                  <span>Logout</span>
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
    </Sidebar>
  );
}
