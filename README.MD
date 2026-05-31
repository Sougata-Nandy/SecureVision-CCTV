# 🔒 SecureVision — Intelligent CCTV Monitoring System

An intelligent, privacy-centric surveillance system built on **Raspberry Pi 5** that uses Edge AI to detect unusual activities in real time — without sending any video data to the cloud.

---

## 🚀 Live Demo

> React dashboard runs locally on your laptop and connects to the Pi via a **Cloudflare Tunnel** — no open ports, no cloud dependency.

---

## 📸 Features

| Detection | Trigger |
|---|---|
| 🔴 **Unauthorized Intrusion** | Person detected during off-hours (10 PM – 6 AM) |
| 🔴 **Fall Detection** | Bounding box flips vertical → horizontal within 4 seconds |
| 🟡 **Loitering Detection** | Person stays in frame for more than 30 seconds |
| 🟡 **Abandoned Object** | Stationary object detected for more than 60 seconds |
| 🔴 **Camera Tampering** | Lens covered, blurred, or camera physically moved |
| 🔴 **Crowd Detection** | 3 or more persons visible at the same time |
| 🟠 **Unusual Activity** | Convolutional Autoencoder detects unknown anomalies via MSE |

**Alert System:**
- 📱 Instant **Telegram notification** with annotated snapshot
- 🎬 **20-second video clip** saved per alert (5s before + 15s after event)
- 📊 All alerts stored in **SQLite database** with timestamp, video offset, and clip filename

---

## 🧠 How It Works

```
Pi Camera → Frame Capture Thread
               ↓
           YOLOv8-Nano  →  Person Detection
           MobileNet-SSD →  Verification Layer    → Rule-Based Detections
               ↓
       Convolutional Autoencoder                  → Anomaly Detection (MSE)
               ↓
         trigger_alert()
               ↓
    ┌─────────────────────────────┐
    │  Save Snapshot              │
    │  Save 20s Alert Clip        │
    │  Store in SQLite            │
    │  Send Telegram Photo        │
    └─────────────────────────────┘
               ↓
       React Dashboard (Live Feed | Alerts | Recordings)
```

---

## 🛠️ Tech Stack

### Pi Backend
| Component | Technology |
|---|---|
| Runtime | Python 3.13, Flask |
| Object Detection | YOLOv8-Nano (Ultralytics) + MobileNet-SSD |
| Anomaly Detection | Convolutional Autoencoder (ONNX Runtime) |
| Person Tracking | Custom Centroid Tracker |
| Video Recording | FFmpeg (H.264, +faststart) |
| Alerts | Telegram Bot API |
| Database | SQLite |
| Remote Access | Cloudflare Tunnel |

### React Dashboard
| Component | Technology |
|---|---|
| Frontend | React.js + TypeScript |
| Styling | Tailwind CSS + shadcn/ui |
| State | TanStack Query |
| Routing | Wouter |
| Auth | MongoDB Atlas |
| Build Tool | Vite |

---

## 📁 Project Structure

```
SecureVision-CCTV/
│
├── pi-backend/                  # Runs on Raspberry Pi 5
│   ├── app.py                   # Main Flask app + all detections
│   ├── centroid_tracker.py      # Person tracking across frames
│   ├── extract_frames.py        # Extract training frames from video
│   ├── train_autoencoder.py     # Train the anomaly detection model
│   └── convert_to_onnx.py       # Convert model for Pi deployment
│
└── dashboard/                   # React frontend (runs on laptop)
    ├── client/src/
    │   ├── pages/
    │   │   ├── live-feed.tsx    # Real-time JPEG snapshot feed
    │   │   ├── unusual-activity.tsx  # Alert cards + video playback
    │   │   └── recordings.tsx   # SSD recording management
    │   └── components/
    ├── package.json
    └── vite.config.ts
```

---

## ⚙️ Setup Guide

### Pi Backend Setup

```bash
# Clone the repo
git clone https://github.com/Sougata-Nandy/SecureVision-CCTV.git
cd SecureVision-CCTV/pi-backend

# Install dependencies
pip install flask flask-cors picamera2 ultralytics opencv-python \
            requests onnxruntime numpy

# Run
python app.py
```

**Configuration** — edit these values in `app.py`:
```python
OFF_HOURS_START  = 22       # off-hours start (10 PM)
OFF_HOURS_END    = 6        # off-hours end (6 AM)
ALERT_COOLDOWN   = 300      # seconds between same alert type
CROWD_THRESHOLD  = 3        # persons to trigger crowd alert
TELEGRAM_TOKEN   = "..."    # your Telegram bot token
TELEGRAM_CHAT_ID = "..."    # your Telegram chat ID
```

### Dashboard Setup

```bash
cd SecureVision-CCTV/dashboard
npm install
npm run dev
```

Update the `TUNNEL` constant in these two files with your Cloudflare tunnel URL:
- `client/src/pages/recordings.tsx`
- `client/src/pages/unusual-activity.tsx`

### Autoencoder Training (on laptop)

```bash
# 1. Record normal footage on Pi (run on Pi)
python record_training.py

# 2. Transfer to laptop, then extract frames
python extract_frames.py

# 3. Train the model
python train_autoencoder.py

# 4. Convert for Pi
python convert_to_onnx.py

# 5. Copy model files to Pi
scp autoencoder.onnx mse_threshold.npy sn1pi@<pi-ip>:/home/sn1pi/smart_cctv/
```

---

## 🔄 System Flow

```
┌─────────────────────────────────────────────────────────┐
│                    Raspberry Pi 5 (Room)                │
│  Pi Camera → app.py → Flask API → Cloudflare Tunnel    │
│  Recordings saved to SSD  │  Alerts saved to SQLite    │
└──────────────────────────────────┬──────────────────────┘
                                   │ HTTPS (Tunnel URL)
                         ┌─────────▼──────────┐
                         │   Your Laptop      │
                         │  React Dashboard   │
                         │  localhost:5173    │
                         └────────────────────┘
```

---

## 📱 Alert Example

When an anomaly is detected:
1. Annotated snapshot saved to `/alerts/` folder on Pi
2. 20-second video clip recorded (5s before + 15s after the event)
3. Photo sent to your Telegram instantly
4. Alert appears on dashboard with one-click video playback

---

## 🔮 Future Work

- [ ] Quantized TFLite model for faster inference on Pi
- [ ] Multi-camera support
- [ ] Adaptive autoencoder retraining during low-activity hours
- [ ] Role-based access for multiple users
- [ ] Adversarial hardening against camera tampering

---

## 👨‍💻 Author

**Sougata Nandy** — MCA Final Year Project  
Ramaiah Institute of Technology, Bengaluru  
[GitHub](https://github.com/Sougata-Nandy) · [LinkedIn](https://linkedin.com/in/sougata-nandy-890ab22aa)

---

## 📄 License

This project is built for academic research and educational purposes.
