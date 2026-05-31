import express from "express";
import bcrypt from "bcrypt";
import User from "../models/User.ts";

const router = express.Router();

// 🧾 Signup route
router.post("/signup", async (req, res) => {
  console.log("📥 Received signup request:", req.body);

  try {
    const { username, email, password } = req.body;

    // 🧠 Validate input
    if (!username || !email || !password) {
      return res.status(400).json({ message: "All fields are required" });
    }

    // 🔎 Check if user already exists
    const existingUser = await User.findOne({ email });
    if (existingUser) {
      return res.status(400).json({ message: "Email already registered" });
    }

    // 🔒 Hash password
    const hashedPassword = await bcrypt.hash(password, 10);

    // 💾 Create new user
    const newUser = new User({
      username,
      email,
      password: hashedPassword,
    });

    await newUser.save();
    console.log(`✅ New user registered: ${username}`);

    res.status(201).json({ message: "Signup successful!" });
  } catch (error) {
    console.error("❌ Signup error:", error);
    res.status(500).json({ message: "Internal server error" });
  }
});

// 🧾 Login route
router.post("/login", async (req, res) => {
  try {
    const { email, password } = req.body;

    // 🧠 Check if email and password are provided
    if (!email || !password) {
      return res.status(400).json({ message: "Email and password are required" });
    }

    // 🔎 Find user by email
    const user = await User.findOne({ email });
    if (!user) {
      return res.status(400).json({ message: "Invalid email or password" });
    }

    // 🔒 Compare passwords
    const isMatch = await bcrypt.compare(password, user.password);
    if (!isMatch) {
      return res.status(400).json({ message: "Invalid email or password" });
    }

    // ✅ Success — login allowed
    console.log(`✅ ${user.username} logged in successfully`);
    res.status(200).json({
      message: "Login successful",
      user: {
        username: user.username,
        email: user.email,
      },
    });
  } catch (error) {
    console.error("❌ Login error:", error);
    res.status(500).json({ message: "Internal server error" });
  }
});


export default router;
