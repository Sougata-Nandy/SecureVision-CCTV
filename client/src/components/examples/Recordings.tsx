import Recordings from "../../pages/recordings";
import { ThemeProvider } from "../theme-provider";

export default function RecordingsExample() {
  return (
    <ThemeProvider>
      <div className="min-h-screen bg-background">
        <Recordings />
      </div>
    </ThemeProvider>
  );
}
