import Login from "../../pages/login";
import { ThemeProvider } from "../theme-provider";

export default function LoginExample() {
  return (
    <ThemeProvider>
      <Login />
    </ThemeProvider>
  );
}
