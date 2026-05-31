import LiveFeed from "../../pages/live-feed";
import { ThemeProvider } from "../theme-provider";

export default function LiveFeedExample() {
  return (
    <ThemeProvider>
      <div className="min-h-screen bg-background">
        <LiveFeed onFullscreenChange={(isFullscreen) => console.log("Fullscreen:", isFullscreen)} />
      </div>
    </ThemeProvider>
  );
}
