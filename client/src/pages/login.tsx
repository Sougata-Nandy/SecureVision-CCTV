import { useState } from "react";
import { useLocation } from "wouter";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { Video } from "lucide-react";
import { useToast } from "@/hooks/use-toast";

export default function Login() {
  const [, setLocation] = useLocation();
  const { toast } = useToast();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [rememberMe, setRememberMe] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
  e.preventDefault();

  if (!email || !password) {
    toast({
      title: "Error",
      description: "Please fill in all fields",
      variant: "destructive",
    });
    return;
  }

  try {
    // 🔥 Send login data to backend
    const res = await fetch("http://localhost:5000/api/login", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ email, password }),
    });

    const data = await res.json();

    if (res.ok) {
      toast({
        title: "Login Successful",
        description: "Redirecting to dashboard...",
      });

      // Optionally, store user info locally for session
      localStorage.setItem("user", JSON.stringify(data.user));

      setTimeout(() => setLocation("/dashboard/live"), 1000);
    } else {
      toast({
        title: "Login Failed",
        description: data.message || "Invalid email or password",
        variant: "destructive",
      });
    }
  } catch (error) {
    console.error("❌ Login error:", error);
    toast({
      title: "Error",
      description: "Could not connect to server",
      variant: "destructive",
    });
  }
};


  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <Card className="w-full max-w-md">
        <CardHeader className="space-y-1">
          <div className="flex items-center justify-center mb-4">
            <div className="flex items-center gap-2">
              <Video className="h-8 w-8 text-primary" />
              <span className="text-2xl font-semibold">SecureVision</span>
            </div>
          </div>
          <CardTitle className="text-2xl text-center">Welcome back</CardTitle>
          <CardDescription className="text-center">
            Enter your credentials to access your dashboard
          </CardDescription>
        </CardHeader>
        <form onSubmit={handleSubmit}>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                placeholder="admin@securevision.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                data-testid="input-email"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                data-testid="input-password"
              />
            </div>
            <div className="flex items-center space-x-2">
              <Checkbox
                id="remember"
                checked={rememberMe}
                onCheckedChange={(checked) => setRememberMe(checked as boolean)}
                data-testid="checkbox-remember"
              />
              <Label
                htmlFor="remember"
                className="text-sm font-normal cursor-pointer"
              >
                Remember me
              </Label>
            </div>
          </CardContent>
          <CardFooter className="flex flex-col gap-4">
            <Button type="submit" className="w-full" data-testid="button-login">
              Sign In
            </Button>
            <div className="text-sm text-center text-muted-foreground">
              Don't have an account?{" "}
              <button
                type="button"
                onClick={() => setLocation("/signup")}
                className="text-primary hover:underline"
                data-testid="link-signup"
              >
                Sign up
              </button>
            </div>
          </CardFooter>
        </form>
      </Card>
    </div>
  );
}
