import { useState } from "react";
import { Switch, Route, Redirect } from "wouter";
import { queryClient } from "./lib/queryClient";
import { QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "@/components/ui/toaster";
import { TooltipProvider } from "@/components/ui/tooltip";
import { SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import { ThemeProvider } from "@/components/theme-provider";
import { ThemeToggle } from "@/components/theme-toggle";
import { AppSidebar } from "@/components/app-sidebar";
import Login from "@/pages/login";
import Signup from "@/pages/signup";
import LiveFeed from "@/pages/live-feed";
import UnusualActivity from "@/pages/unusual-activity";
import Recordings from "@/pages/recordings";
import NotFound from "@/pages/not-found";

function LiveFeedPage() {
  const [sidebarOpen, setSidebarOpen] = useState(true);
  
  const style = {
    "--sidebar-width": "16rem",
    "--sidebar-width-icon": "3rem",
  };

  const handleFullscreenChange = (isFullscreen: boolean) => {
    setSidebarOpen(!isFullscreen);
  };

  return (
    <SidebarProvider 
      style={style as React.CSSProperties}
      open={sidebarOpen}
      onOpenChange={setSidebarOpen}
    >
      <div className="flex h-screen w-full">
        <AppSidebar />
        <div className="flex flex-col flex-1 overflow-hidden">
          <header className="flex items-center justify-between p-4 border-b">
            <SidebarTrigger data-testid="button-sidebar-toggle" />
            <ThemeToggle />
          </header>
          <main className="flex-1 overflow-auto">
            <LiveFeed onFullscreenChange={handleFullscreenChange} />
          </main>
        </div>
      </div>
    </SidebarProvider>
  );
}

function DashboardLayout({ children }: { children: React.ReactNode }) {
  const style = {
    "--sidebar-width": "16rem",
    "--sidebar-width-icon": "3rem",
  };

  return (
    <SidebarProvider style={style as React.CSSProperties}>
      <div className="flex h-screen w-full">
        <AppSidebar />
        <div className="flex flex-col flex-1 overflow-hidden">
          <header className="flex items-center justify-between p-4 border-b">
            <SidebarTrigger data-testid="button-sidebar-toggle" />
            <ThemeToggle />
          </header>
          <main className="flex-1 overflow-auto">
            {children}
          </main>
        </div>
      </div>
    </SidebarProvider>
  );
}

function Router() {
  return (
    <Switch>
      <Route path="/" component={() => <Redirect to="/login" />} />
      <Route path="/login" component={Login} />
      <Route path="/signup" component={Signup} />
      <Route path="/dashboard/live" component={LiveFeedPage} />
      <Route path="/dashboard/alerts">
        <DashboardLayout>
          <UnusualActivity />
        </DashboardLayout>
      </Route>
      <Route path="/dashboard/recordings">
        <DashboardLayout>
          <Recordings />
        </DashboardLayout>
      </Route>
      <Route path="/dashboard">
        <Redirect to="/dashboard/live" />
      </Route>
      <Route component={NotFound} />
    </Switch>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider defaultTheme="dark">
        <TooltipProvider>
          <Router />
          <Toaster />
        </TooltipProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
