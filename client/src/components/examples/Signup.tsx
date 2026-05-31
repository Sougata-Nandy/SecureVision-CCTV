import Signup from "../../pages/signup";
import { ThemeProvider } from "../theme-provider";

export default function SignupExample() {
  return (
    <ThemeProvider>
      <Signup />
    </ThemeProvider>
  );
}
