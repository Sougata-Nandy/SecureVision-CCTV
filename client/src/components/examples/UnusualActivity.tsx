import UnusualActivity from "../../pages/unusual-activity";
import { ThemeProvider } from "../theme-provider";

export default function UnusualActivityExample() {
  return (
    <ThemeProvider>
      <div className="min-h-screen bg-background">
        <UnusualActivity />
      </div>
    </ThemeProvider>
  );
}
