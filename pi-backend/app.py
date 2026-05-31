import cv2
import onnxruntime as ort
import threading
import numpy as np
import os
import time
import subprocess
import atexit
import shutil
import signal
import sys
import sqlite3
from collections import deque
import requests
from flask import Flask, Response, jsonify, request, send_from_directory
from flask_cors import CORS
from picamera2 import Picamera2
from ultralytics import YOLO
from datetime import datetime, timedelta
# --- CENTROID TRACKER ---
from centroid_tracker import CentroidTracker


app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# --- CONFIGURATION ---
SSD_PATH         = "/home/sn1pi/smart_cctv/recordings"
SNAPSHOT_PATH    = "/home/sn1pi/smart_cctv/snapshot.jpg"
SEGMENT_DURATION = 6 * 60 * 60   # 6 hours
WIDTH, HEIGHT, FPS = 640, 480, 20
SNAPSHOT_INTERVAL  = 0.2          # seconds between snapshot JPEGs (5 fps live view)
MAX_DISK_PERCENT   = 90           # start deleting oldest files above this %
MIN_DISK_PERCENT   = 80           # stop deleting once usage is back below this %
# --- INTRUSION DETECTION CONFIG ---
OFF_HOURS_START = 22        # 10:00 PM  Ã¢â€  change to your preferred off-hours start
OFF_HOURS_END   = 6         # 06:00 AM  Ã¢â€  change to your preferred off-hours end
ALERT_COOLDOWN  = 300        # seconds before the same alert type can fire again
LOITER_THRESHOLD = 30   # seconds a person must stay before loitering alert fires
FALL_RATIO_THRESHOLD = 1.2   # width/height above this = person is horizontal (fallen)
FALL_STANDING_RATIO  = 0.8   # width/height below this = person is clearly standing
MIN_BBOX_HEIGHT      = 80    # ignore bounding boxes shorter than this (px)
FALL_TIME_WINDOW     = 4     # seconds Ã¢â‚¬â€ must go from standing to fallen within this time to count as a fall
ABANDON_THRESHOLD    = 60    # seconds a blob must stay stationary to trigger alert
ABANDON_MIN_AREA     = 2500  # minimum blob size in pixelsÃ‚Â² (filters out noise/shadows)
ABANDON_GRID         = 50    # grid cell size (px) for matching blobs across frames
CLIP_BEFORE_SECS    = 5     # seconds BEFORE alert to include in clip
CLIP_AFTER_SECS     = 15    # seconds AFTER  alert to include in clip
TAMPER_DARK_THRESHOLD  = 15    # mean brightness below this â†’ lens covered (0-255 scale)
TAMPER_BLUR_THRESHOLD  = 30    # Laplacian variance below this â†’ blurry/spray painted
TAMPER_SCENE_THRESHOLD = 55    # mean pixel diff vs reference â†’ camera moved/rotated
TAMPER_SCENE_FRAMES    = 30    # consecutive high-diff frames needed to fire alert (~1.5s)
TAMPER_REF_UPDATE_SECS = 300   # update reference frame every 5 min when scene is clear
CROWD_THRESHOLD = 3    # alert when this many or more persons visible at once
ALERTS_PATH     = "/home/sn1pi/smart_cctv/alerts"
# --- AUTOENCODER CONFIG ---
AE_MODEL_PATH     = "/home/sn1pi/smart_cctv/autoencoder.onnx"
AE_THRESHOLD_PATH = "/home/sn1pi/smart_cctv/mse_threshold.npy"
AE_RUN_EVERY      = 30
AE_ENABLED        = True
os.makedirs(ALERTS_PATH, exist_ok=True)
# --- SQLITE + TELEGRAM CONFIG ---
DB_PATH           = "/home/sn1pi/smart_cctv/alerts.db"
TELEGRAM_TOKEN    = "8977334133:AAELV6hwGmEet-celbdiQtKkBuWpYLXu8qg"    # â† paste your BotFather token
TELEGRAM_CHAT_ID  = "6610852222"      # â† paste your chat ID
TELEGRAM_ENABLED  = True                     # â† set False to disable Telegram temporarily


os.makedirs(SSD_PATH, exist_ok=True)

# 1. AI MODELS
yolo_model = YOLO('yolov8n.pt')
net = cv2.dnn.readNetFromCaffe(
    'models/deploy.prototxt',
    'models/mobilenet_iter_73000.caffemodel'
)
CLASSES = [
    "background","aeroplane","bicycle","bird","boat","bottle","bus","car",
    "cat","chair","cow","diningtable","dog","horse","motorbike","person",
    "pottedplant","sheep","sofa","train","tvmonitor"
]

# 2. CAMERA
picam2 = Picamera2()
picam2.configure(picam2.create_video_configuration(main={"size": (WIDTH, HEIGHT)}))
picam2.start()

latest_frame    = None
processed_frame = None
lock            = threading.Lock()

# --- TRACKER INSTANCE ---
# max_disappeared=20 means a person can vanish for 20 frames (~1 second)
# before their ID is dropped. Increase if you get ID flickering.
tracker = CentroidTracker(max_disappeared=20)

# Stores the FIRST time each person ID was seen Ã¢â‚¬â€ used for loitering detection later
person_first_seen = {}   # { person_id: timestamp }
# Cooldown tracker Ã¢â‚¬â€ prevents alert spam
# { "Unauthorized Intrusion": 1714589432.1, "Fall Detected": ... }
last_alert_time = {}
# Stores the last timestamp when each person was clearly standing
# If they go horizontal within FALL_TIME_WINDOW seconds of this Ã¢â€ â€™ real fall
person_last_standing = {}   # { person_id: timestamp }
# Background subtractor Ã¢â‚¬â€ learns the "normal" empty scene over time
# history=500 : uses last 500 frames to build background model
# varThreshold : sensitivity Ã¢â‚¬â€ higher = less sensitive to small changes
# detectShadows: marks shadows as gray (127) so we can filter them out
bg_subtractor    = cv2.createBackgroundSubtractorMOG2(history=500, varThreshold=50, detectShadows=True)
# Warmup: skip abandoned object detection for first 30 seconds
# while background model is still learning the scene
bg_warmup_until  = time.time() + 30

# Tracks stationary foreground blobs across frames
# Key = "gridX_gridY" (centroid snapped to grid for stable matching)
# Value = { "first_seen": timestamp, "bbox": (x1, y1, x2, y2) }
static_objects   = {}

# Pre-built morphological kernel Ã¢â‚¬â€ created once, reused every frame
# Avoids rebuilding the same 5Ãƒâ€”5 ellipse kernel ~20 times per second
morph_kernel     = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))

# Load autoencoder model
ae_session     = None
ae_input_name  = None
ae_threshold   = None
ae_frame_count = 0

if AE_ENABLED:
    try:
        ae_session    = ort.InferenceSession(AE_MODEL_PATH)
        ae_input_name = ae_session.get_inputs()[0].name
        ae_threshold  = float(np.load(AE_THRESHOLD_PATH)[0])
        ae_threshold  = ae_threshold * 0.7   # ← lower = more sensitive
        print(f"[AE] Autoencoder loaded — threshold: {ae_threshold:.6f}")
    except Exception as e:
        print(f"[AE] Could not load model: {e}")
        AE_ENABLED = False


# Rolling frame buffer â€” keeps last CLIP_BEFORE_SECS * FPS clean frames
# Frames stored as JPEG bytes (~20-50KB each) to keep RAM usage low
# At 20fps Ã— 5s = 100 frames Ã— ~30KB = ~3MB RAM
frame_buffer = deque(maxlen=int(CLIP_BEFORE_SECS * FPS))

# Threading lock â€” ensures only one alert writes to SQLite at a time
db_lock = threading.Lock()

def init_db():
    """
    Create / migrate the alerts table.
    - Detects and replaces old wrong schema (alert_type, image_path)
    - Adds clip_filename column to existing correct-schema databases
    """
    conn = sqlite3.connect(DB_PATH)

    # Check existing columns
    existing_cols = [
        row[1] for row in conn.execute("PRAGMA table_info(alerts)").fetchall()
    ]

    # Old wrong schema had 'alert_type' â€” drop and recreate
    if existing_cols and "alert_type" in existing_cols:
        conn.execute("DROP TABLE alerts")
        conn.commit()
        existing_cols = []
        print("[DB] Old schema removed â€” recreating with correct schema")

    # Create table with correct full schema
    conn.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            activity_type     TEXT    NOT NULL,
            timestamp         TEXT    NOT NULL,
            video_file        TEXT    NOT NULL,
            snapshot_filename TEXT    NOT NULL,
            alert_offset_s    INTEGER NOT NULL,
            clip_filename     TEXT    DEFAULT ''
        )
    """)

    # Add clip_filename to existing DBs that don't have it yet
    existing_cols = [
        row[1] for row in conn.execute("PRAGMA table_info(alerts)").fetchall()
    ]
    if "clip_filename" not in existing_cols:
        conn.execute("ALTER TABLE alerts ADD COLUMN clip_filename TEXT DEFAULT ''")
        print("[DB] Added clip_filename column to existing table")

    conn.commit()
    conn.close()
    print("[DB] alerts.db ready")

init_db()


# Camera tamper detection globals
tamper_ref_frame     = None   # grayscale reference snapshot of the "normal" scene
tamper_ref_updated   = 0.0    # timestamp of last reference update
tamper_scene_counter = 0      # consecutive frames with high scene diff (for sustained check)



# ---------------------------------------------------------------------------
# 3. SSD RECORDER with Auto-Cleanup
#    manage_storage() is called every time a new segment starts (every 6h).
#    It deletes the oldest .mp4 files until disk usage drops below
#    MIN_DISK_PERCENT, so the SSD never fills up and crashes the system.
# ---------------------------------------------------------------------------
class VideoRecorder:
    def __init__(self):
        self.process      = None
        self.start_time   = 0
        self.current_file = ""

    def manage_storage(self):
        """Delete oldest recordings if disk usage exceeds MAX_DISK_PERCENT."""
        try:
            total, used, _ = shutil.disk_usage(SSD_PATH)
            percent_used = (used / total) * 100

            if percent_used <= MAX_DISK_PERCENT:
                return  # plenty of space, nothing to do

            print(f"Storage Warning: Disk is {percent_used:.1f}% full. Cleaning up...")

            # Collect all .mp4 files sorted oldest-first
            files = []
            for f in os.listdir(SSD_PATH):
                if f.endswith(".mp4"):
                    fpath = os.path.join(SSD_PATH, f)
                    # Skip the file currently being recorded
                    if fpath == self.current_file:
                        continue
                    files.append((fpath, os.path.getctime(fpath)))
            files.sort(key=lambda x: x[1])  # oldest first

            for fpath, _ in files:
                if percent_used <= MIN_DISK_PERCENT:
                    break
                try:
                    os.remove(fpath)
                    print(f"Auto-deleted old recording: {os.path.basename(fpath)}")
                    total, used, _ = shutil.disk_usage(SSD_PATH)
                    percent_used = (used / total) * 100
                except Exception as e:
                    print(f"Error deleting {fpath}: {e}")

        except Exception as e:
            print(f"manage_storage error: {e}")

    def _start(self):
        # Run cleanup BEFORE starting a new heavy recording segment
        self.manage_storage()

        if self.process and self.process.poll() is None:
            try:
                self.process.stdin.close()
                self.process.wait(timeout=5)
            except Exception:
                pass
            print(f"SSD segment saved: {self.current_file}")
            self._cleanup_clips()   # segment complete â†’ clips no longer needed


        ts = time.strftime("%Y%m%d_%H%M%S")
        self.current_file = os.path.join(SSD_PATH, f"cam1_{ts}.mp4")

        cmd = [
            "ffmpeg", "-y",
            "-f", "rawvideo", "-vcodec", "rawvideo",
            "-pix_fmt", "bgr24",
            "-s", f"{WIDTH}x{HEIGHT}",
            "-r", str(FPS),
            "-i", "pipe:0",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            self.current_file
        ]
        self.process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        self.start_time = time.time()
        print(f"SSD recording started: {self.current_file}")

    def write(self, frame):
        if (self.process is None
                or self.process.poll() is not None
                or (time.time() - self.start_time) >= SEGMENT_DURATION):
            self._start()
        try:
            self.process.stdin.write(frame.tobytes())
        except Exception:
            self._start()

    def get_current_file(self):
        if self.process and self.process.poll() is None and self.current_file:
            return self.current_file
        return None
    
    def _cleanup_clips(self):
        """
        Deletes temporary 20-second alert clips from ALERTS_PATH.
        Called when a 6h segment ends OR when Pi shuts down.
        After this, old alerts use the completed recording + alert_offset_s to seek.
        """
        try:
            deleted = 0
            for fname in os.listdir(ALERTS_PATH):
                if fname.startswith("clip_") and fname.endswith(".mp4"):
                    try:
                        os.remove(os.path.join(ALERTS_PATH, fname))
                        deleted += 1
                    except Exception:
                        pass
            if deleted:
                # Also clear clip_filename in SQLite so React falls back to offset-based seek
                try:
                    conn = sqlite3.connect(DB_PATH)
                    conn.execute("UPDATE alerts SET clip_filename = '' WHERE clip_filename != ''")
                    conn.commit()
                    conn.close()
                except Exception as e:
                    print(f"[CLIP] DB clear error: {e}")
                print(f"[CLIP] Cleaned up {deleted} clip(s) â€” alerts now use offset-based seek")

        except Exception as e:
            print(f"[CLIP] Cleanup error: {e}")



    def finalize(self):
        if self.process and self.process.poll() is None:
            try:
                self.process.stdin.close()
                self.process.wait(timeout=10)
                print(f"SSD final segment saved: {self.current_file}")
            except Exception:
                pass

recorder = VideoRecorder()

# ---------------------------------------------------------------------------
# 4. SNAPSHOT WRITER
#    Every SNAPSHOT_INTERVAL seconds, encodes the latest AI-annotated frame
#    as JPEG and atomically writes it to disk. Flask serves it at /snapshot.
#    The React frontend polls this URL for the live feed.
# ---------------------------------------------------------------------------
class SnapshotWriter:
    def __init__(self, path):
        self.path         = path
        self.last_written = 0

    def write(self, frame):
        now = time.time()
        if now - self.last_written < SNAPSHOT_INTERVAL:
            return
        ret, buf = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
        if not ret:
            return
        tmp = self.path + ".tmp"
        try:
            with open(tmp, 'wb') as f:
                f.write(buf.tobytes())
            os.replace(tmp, self.path)
            self.last_written = now
        except Exception as e:
            print(f"Snapshot write error: {e}")

snapshot_writer = SnapshotWriter(SNAPSHOT_PATH)

# ---------------------------------------------------------------------------
# 5. CAMERA CAPTURE THREAD
# ---------------------------------------------------------------------------
def camera_capture_worker():
    global latest_frame
    print("Camera thread: started")
    while True:
        try:
            frame = picam2.capture_array()
            if frame is not None:
                frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                with lock:
                    latest_frame = frame
        except Exception as e:
            print(f"Camera error: {e}")
            time.sleep(0.1)

threading.Thread(target=camera_capture_worker, daemon=True).start()



def send_telegram(caption, image_path):
    """Send annotated alert image to Telegram bot."""
    if not TELEGRAM_ENABLED:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
        with open(image_path, 'rb') as photo:
            resp = requests.post(
                url,
                data  = {'chat_id': TELEGRAM_CHAT_ID, 'caption': caption},
                files = {'photo': photo},
                timeout = 10
            )
        if resp.status_code == 200:
            print(f"[TELEGRAM] Alert sent successfully")
        else:
            print(f"[TELEGRAM] Failed ({resp.status_code}): {resp.text}")
    except Exception as e:
        print(f"[TELEGRAM] Error: {e}")


def _save_clip(before_frames, clip_path):
    """
    Runs in a background thread â€” non-blocking.
    Writes before_frames (ring buffer snapshot) + CLIP_AFTER_SECS of live
    frames into a standalone, complete, immediately playable MP4 clip.
    Uses +faststart so the moov atom is at the front â†’ browser can play it.
    """
    cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo", "-vcodec", "rawvideo",
        "-pix_fmt", "bgr24",
        "-s", f"{WIDTH}x{HEIGHT}",
        "-r", str(FPS),
        "-i", "pipe:0",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        clip_path
    ]
    try:
        proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        # Write the before-frames (JPEG â†’ raw BGR)
        for buf in before_frames:
            frame = cv2.imdecode(np.frombuffer(buf, np.uint8), cv2.IMREAD_COLOR)
            if frame is not None:
                try:
                    proc.stdin.write(frame.tobytes())
                except Exception:
                    break
        # Write after-frames (live capture for CLIP_AFTER_SECS)
        end_t = time.time() + CLIP_AFTER_SECS
        while time.time() < end_t:
            with lock:
                af = latest_frame.copy() if latest_frame is not None else None
            if af is not None:
                try:
                    proc.stdin.write(af.tobytes())
                except Exception:
                    break
            time.sleep(1.0 / FPS)
        proc.stdin.close()
        proc.wait(timeout=60)
        print(f"[CLIP] Saved: {os.path.basename(clip_path)}")
    except Exception as e:
        print(f"[CLIP] Error: {e}")


# ---------------------------------------------------------------------------
# ALERT TRIGGER â€” saves snapshot + SQLite record + sends Telegram photo
# ---------------------------------------------------------------------------
def trigger_alert(activity_type, frame, bbox=None):
    """
    Called whenever unusual activity is detected.
    1. Cooldown check      â€” prevents spam alerts
    2. Annotates frame     â€” red banner + bounding box
    3. Saves snapshot      â€” to ALERTS_PATH folder
    4. Saves to SQLite     â€” with video file + offset for auto-seek
    5. Sends Telegram      â€” annotated photo to your phone
    """
    now = time.time()

    # â”€â”€ 1. Cooldown check â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if now - last_alert_time.get(activity_type, 0) < ALERT_COOLDOWN:
        return
    last_alert_time[activity_type] = now

    # â”€â”€ 2. Annotate the frame â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    alert_frame = frame.copy()
    ts_label    = time.strftime("%Y-%m-%d %H:%M:%S")

    if bbox:
        x1, y1, x2, y2 = bbox
        cv2.rectangle(alert_frame, (x1, y1), (x2, y2), (0, 0, 255), 3)

    cv2.rectangle(alert_frame, (0, 0), (640, 50), (0, 0, 200), -1)
    cv2.putText(alert_frame, f"ALERT: {activity_type}",
                (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
    cv2.putText(alert_frame, ts_label,
                (10, 45), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)

    # â”€â”€ 3. Save snapshot â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    ts_file  = time.strftime("%Y%m%d_%H%M%S")
    filename = f"{activity_type.replace(' ', '_')}_{ts_file}.jpg"
    filepath = os.path.join(ALERTS_PATH, filename)
    cv2.imwrite(filepath, alert_frame)

    # â”€â”€ 4. Capture video position for auto-seek (kept for old alerts) â”€â”€â”€â”€â”€â”€
    alert_offset_s = int(now - recorder.start_time) if recorder.start_time else 0
    video_file     = os.path.basename(recorder.current_file or "")

    # â”€â”€ 5. Save alert clip (20s: 5s before + 15s after the event) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    #    Runs in a background thread so it doesn't block the detection loop.
    #    The clip is a complete standalone MP4 â€” playable immediately.
    clip_filename = f"clip_{activity_type.replace(' ', '_')}_{ts_file}.mp4"
    clip_path     = os.path.join(ALERTS_PATH, clip_filename)
    before_frames = list(frame_buffer)   # snapshot of ring buffer at alert time
    threading.Thread(
        target=_save_clip,
        args=(before_frames, clip_path),
        daemon=True
    ).start()

    # â”€â”€ 6. Save to SQLite â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    with db_lock:
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.execute(
                """INSERT INTO alerts
                   (activity_type, timestamp, video_file, snapshot_filename,
                    alert_offset_s, clip_filename)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (activity_type, ts_label, video_file, filename,
                 alert_offset_s, clip_filename)
            )
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[DB] Error saving alert: {e}")

    # â”€â”€ 6. Send Telegram â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    send_telegram(
        caption   = f"ðŸš¨ {activity_type}\nðŸ“… {ts_label}\nðŸ“¹ {video_file}\nâ± Offset: {alert_offset_s}s",
        image_path = filepath
    )

    # â”€â”€ 7. Console log â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    print(f"[ALERT] {activity_type} | {ts_label} | Offset: {alert_offset_s}s | {filename}")


# ---------------------------------------------------------------------------
# 6. AI + RECORDING + SNAPSHOT WORKER
# ---------------------------------------------------------------------------
def background_worker():
    global processed_frame, ae_frame_count
    print("AI thread: started")
    while True:
        with lock:
            frame = latest_frame.copy() if latest_frame is not None else None

        if frame is None:
            time.sleep(0.01)
            continue

        # Write clean frame (no boxes) to SSD
        recorder.write(frame)

        # Add JPEG-compressed clean frame to rolling buffer
        # Captured BEFORE YOLO annotations so clip looks clean
        _, _buf = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        frame_buffer.append(bytes(_buf))

        h, w = frame.shape[:2]


        # YOLO person detection + centroid tracker
        rects = []   # will hold (x1, y1, x2, y2) for each detected person

        for r in yolo_model(frame, stream=True, conf=0.4, classes=[0], verbose=False):
            frame = r.plot()   # draw YOLO boxes (same as before Ã¢â‚¬â€ no change)
            for box in r.boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                rects.append((x1, y1, x2, y2))

        # Update tracker Ã¢â‚¬â€ gives back { id: centroid } and { id: bbox }
        objects, bboxes = tracker.update(rects)

        # Record first-seen time for any new person ID
        for person_id in objects:
            if person_id not in person_first_seen:
                person_first_seen[person_id] = time.time()


        # Ã¢â€â‚¬Ã¢â€â‚¬ INTRUSION DETECTION Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
        # Check if current time is within off-hours
        hour = datetime.now().hour
        is_off_hours = (hour >= OFF_HOURS_START or hour < OFF_HOURS_END)

        if is_off_hours and len(objects) > 0:
            # Take the first detected person's bounding box for the alert snapshot
            first_id   = next(iter(bboxes))
            alert_bbox = bboxes[first_id]
            trigger_alert("Unauthorized Intrusion", frame, alert_bbox)


        # Ã¢â€â‚¬Ã¢â€â‚¬ LOITERING DETECTION Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
        now = time.time()
        for person_id, bbox in bboxes.items():
            time_in_frame = now - person_first_seen.get(person_id, now)
            if time_in_frame >= LOITER_THRESHOLD:
                trigger_alert("Loitering Detected", frame, bbox)
                break   # one alert per frame is enough


        # ── CROWD DETECTION ───────────────────────────────────────────────────
        # len(objects) = number of persons CURRENTLY visible in frame
        # This is NOT the cumulative ID count — only active tracked persons
        if len(objects) >= CROWD_THRESHOLD:
            trigger_alert("Crowd Detected", frame)

        
        # Ã¢â€â‚¬Ã¢â€â‚¬ FALL DETECTION (with time-window) Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
        now_fall = time.time()
        for person_id, bbox in bboxes.items():
            x1, y1, x2, y2 = bbox
            bw = x2 - x1   # renamed: was w Ã¢â‚¬â€ avoids shadowing frame width
            bh = y2 - y1   # renamed: was h Ã¢â‚¬â€ avoids shadowing frame height

            # Skip tiny/unreliable detections
            if bh < MIN_BBOX_HEIGHT:
                continue

            ratio = bw / bh   # < 1 = tall (standing), > 1 = wide (fallen/lying)

            # Every frame the person is clearly standing Ã¢â€ â€™ update their standing timestamp
            if ratio < FALL_STANDING_RATIO:
                person_last_standing[person_id] = now_fall

            # Check if person is now horizontal (potentially fallen)
            if ratio > FALL_RATIO_THRESHOLD:
                last_stood = person_last_standing.get(person_id)

                if last_stood is not None:
                    time_since_standing = now_fall - last_stood

                    if time_since_standing <= FALL_TIME_WINDOW:
                        # Was standing recently AND now horizontal Ã¢â€ â€™ REAL FALL
                        trigger_alert("Fall Detected", frame, bbox)
                    # else: took too long Ã¢â€ â€™ sleeping/lying down deliberately Ã¢â€ â€™ ignore

                # else: no standing record (walked in already lying) Ã¢â€ â€™ ignore

            # Visual indicator on live feed
            # Ã°Å¸â€Â´ Red dot = currently horizontal   Ã°Å¸Å¸Â¢ Green dot = standing
            fall_cx, fall_cy = (x1 + x2) // 2, (y1 + y2) // 2
            dot_color = (0, 0, 255) if ratio > FALL_RATIO_THRESHOLD else (0, 255, 0)
            cv2.circle(frame, (fall_cx, fall_cy), 6, dot_color, -1)

        # ── AUTOENCODER ANOMALY DETECTION ─────────────────────────────────────
        # Runs every 60 frames (~3 seconds) to save CPU on Pi.
        # Only runs when no persons are detected to avoid false alarms
        # from normal human movement triggering the detector.
        # Catches things rule-based detectors miss:
        # fire, smoke, flooding, scene damage, unexpected objects etc.
        if AE_ENABLED and ae_session is not None:
            ae_frame_count += 1
            if ae_frame_count % AE_RUN_EVERY == 0 and len(objects) == 0:
                try:
                    small = cv2.resize(frame, (64, 64))
                    small = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
                    inp   = small.astype("float32") / 255.0
                    inp   = np.expand_dims(inp, 0)
                    recon = ae_session.run(None, {ae_input_name: inp})[0]
                    mse   = float(np.mean(np.square(inp - recon)))
                    if mse > ae_threshold:
                        trigger_alert("Unusual Activity", frame)
                        print(f"[AE] Anomaly! MSE={mse:.6f} threshold={ae_threshold:.6f}")
                except Exception as e:
                    print(f"[AE] Error: {e}")



        # Ã¢â€â‚¬Ã¢â€â‚¬ ABANDONED OBJECT DETECTION Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
        now_obj = time.time()
        fg_mask = bg_subtractor.apply(frame)

        # Threshold: keep only definite foreground (255)
        # Shadows are marked 127 by MOG2 Ã¢â‚¬â€ we discard them here
        _, fg_mask = cv2.threshold(fg_mask, 200, 255, cv2.THRESH_BINARY)

        # Morphological cleanup:
        # OPEN  = erode then dilate  Ã¢â€ â€™ removes tiny noise dots
        # CLOSE = dilate then erode  Ã¢â€ â€™ fills small holes inside blobs
        fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_OPEN,  morph_kernel)
        fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_CLOSE, morph_kernel)

        contours, _ = cv2.findContours(
            fg_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        seen_keys = set()

        # Only run detection after warmup period
        if now_obj > bg_warmup_until:
            for cnt in contours:
                area = cv2.contourArea(cnt)
                if area < ABANDON_MIN_AREA:
                    continue   # too small Ã¢â€ â€™ shadow remnant or noise

                # Bounding box and centroid of this blob
                bx, by, bw, bh = cv2.boundingRect(cnt)
                cx, cy = bx + bw // 2, by + bh // 2

                # Skip if this blob overlaps with a tracked person's bounding box
                # (we don't want to flag a standing/sitting person as abandoned object)
                is_person = any(
                    px1 <= cx <= px2 and py1 <= cy <= py2
                    for (px1, py1, px2, py2) in bboxes.values()
                )
                if is_person:
                    continue

                # Snap centroid to grid Ã¢â€ â€™ stable key even if blob shifts a few pixels
                gx  = (cx // ABANDON_GRID) * ABANDON_GRID
                gy  = (cy // ABANDON_GRID) * ABANDON_GRID
                key = f"{gx}_{gy}"
                seen_keys.add(key)

                if key not in static_objects:
                    # First time we see this blob Ã¢â€ â€™ record it
                    static_objects[key] = {
                        "first_seen": now_obj,
                        "bbox": (bx, by, bx + bw, by + bh)
                    }
                else:
                    time_stationary = now_obj - static_objects[key]["first_seen"]
                    ox1, oy1, ox2, oy2 = static_objects[key]["bbox"]

                    # Yellow box on live feed once object has been there > half threshold
                    # Gives you a visual heads-up before the alert fires
                    if time_stationary > ABANDON_THRESHOLD / 2:
                        cv2.rectangle(frame, (ox1, oy1), (ox2, oy2), (0, 255, 255), 2)
                        cv2.putText(frame, f"Static {int(time_stationary)}s",
                                    (ox1, oy1 - 8),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)

                    # Fire alert once threshold is reached
                    if time_stationary >= ABANDON_THRESHOLD:
                        trigger_alert("Abandoned Object", frame, (ox1, oy1, ox2, oy2))

            # Remove blobs that disappeared (object was picked up / person moved it)
            for key in list(static_objects.keys()):
                if key not in seen_keys:
                    del static_objects[key]


        # Ã¢â€â‚¬Ã¢â€â‚¬ CLEANUP: remove IDs that are no longer tracked Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
        tracked_ids = set(objects.keys())
        for pid in list(person_first_seen.keys()):
            if pid not in tracked_ids:
                del person_first_seen[pid]
        for pid in list(person_last_standing.keys()):
            if pid not in tracked_ids:
                del person_last_standing[pid]



        # â”€â”€ CAMERA TAMPERING DETECTION â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        global tamper_ref_frame, tamper_ref_updated, tamper_scene_counter

        gray  = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        now_t = time.time()

        # â”€â”€ Check 1: Darkness â†’ lens covered by hand / tape / cloth â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        brightness = float(np.mean(gray))
        if brightness < TAMPER_DARK_THRESHOLD:
            trigger_alert("Camera Tampered", frame)

        # â”€â”€ Check 2: Blur â†’ lens spray painted, smeared, or defocused â”€â”€â”€â”€â”€â”€â”€â”€
        blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        if blur_score < TAMPER_BLUR_THRESHOLD:
            trigger_alert("Camera Tampered", frame)

        # â”€â”€ Check 3: Scene change â†’ camera physically moved or rotated â”€â”€â”€â”€â”€â”€â”€â”€
        if tamper_ref_frame is None:
            # First frame â€” store it as reference and start the clock
            tamper_ref_frame   = gray.copy()
            tamper_ref_updated = now_t
        else:
            scene_diff = float(np.mean(cv2.absdiff(gray, tamper_ref_frame)))

            if scene_diff > TAMPER_SCENE_THRESHOLD:
                # Scene looks different from reference â†’ increment sustained counter
                tamper_scene_counter += 1
                if tamper_scene_counter >= TAMPER_SCENE_FRAMES:
                    # Stayed different for 30+ consecutive frames â†’ real tamper, not just motion
                    trigger_alert("Camera Tampered", frame)
            else:
                # Scene matches reference â†’ reset counter
                tamper_scene_counter = 0

                # Update reference only when: no persons in frame + enough time has passed
                # This ensures reference always reflects a clean, person-free scene
                if (len(objects) == 0 and
                        now_t - tamper_ref_updated > TAMPER_REF_UPDATE_SECS):
                    tamper_ref_frame   = gray.copy()
                    tamper_ref_updated = now_t
                    print("[TAMPER] Reference frame updated")





        # Draw person IDs Ã¢â‚¬â€ circle already drawn (colour-coded) by fall detection above
        for (person_id, centroid) in objects.items():
            cx, cy = centroid
            cv2.putText(frame, f"ID {person_id}", (cx - 10, cy - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)


        # MobileNet SSD
        blob = cv2.dnn.blobFromImage(
            cv2.resize(frame, (300, 300)), 0.007843, (300, 300), 127.5
        )
        net.setInput(blob)
        detections = net.forward()
        for i in range(detections.shape[2]):
            if detections[0, 0, i, 2] > 0.5:
                cid = int(detections[0, 0, i, 1])
                if CLASSES[cid] == "person":
                    box = detections[0, 0, i, 3:7] * np.array([w, h, w, h])
                    sx, sy, ex, ey = box.astype("int")
                    cv2.rectangle(frame, (sx, sy), (ex, ey), (0, 255, 0), 2)

        # Write AI-annotated frame as snapshot for live view
        snapshot_writer.write(frame)

        with lock:
            processed_frame = frame

threading.Thread(target=background_worker, daemon=True).start()


def get_severity(activity_type):
    """
    Maps activity type to a severity level for the React dashboard badge colours.
    high   â†’ red    (dangerous / urgent)
    medium â†’ yellow (suspicious)
    low    â†’ blue   (informational)
    """
    if activity_type in ["Fall Detected", "Unauthorized Intrusion", "Camera Tampered"]:
        return "high"
    if activity_type in ["Loitering Detected", "Abandoned Object"]:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# 7. FLASK ROUTES
# ---------------------------------------------------------------------------

@app.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"]   = "*"
    response.headers["Access-Control-Allow-Methods"]  = "GET, OPTIONS"
    response.headers["Access-Control-Allow-Headers"]  = "Range, Content-Type"
    response.headers["Access-Control-Expose-Headers"] = \
        "Content-Range, Content-Length, Accept-Ranges"
    return response



@app.route('/api/alerts')
def list_alerts():
    """
    Returns all alerts from SQLite as JSON, newest first.
    Supports ?filter=today|24h|week  (matches the React dropdown)

    Each alert object contains everything the React dashboard needs:
      - activity_type + severity  â†’ badge colour and label
      - timestamp                 â†’ displayed on card
      - snapshot_filename         â†’ used to build thumbnail URL
      - video_file + offset       â†’ used for auto-seek playback
    """
    try:
        filter_val = request.args.get('filter', 'today')
        now        = datetime.now()

        # Build time filter
        if filter_val == 'today':
            since = now.strftime('%Y-%m-%d') + ' 00:00:00'
        elif filter_val == '24h':
            since = (now - timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S')
        elif filter_val == 'week':
            since = (now - timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')
        else:
            since = None   # fallback â€” return all

        conn             = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row  # lets us access columns by name

        if since:
            rows = conn.execute(
                "SELECT * FROM alerts WHERE timestamp >= ? ORDER BY id DESC",
                (since,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM alerts ORDER BY id DESC LIMIT 100"
            ).fetchall()

        conn.close()

        result = [
            {
                "id":                str(row["id"]),
                "activity_type":     row["activity_type"],
                "timestamp":         row["timestamp"],
                "video_file":        row["video_file"],
                "snapshot_filename": row["snapshot_filename"],
                "alert_offset_s":    row["alert_offset_s"],
                "severity":          get_severity(row["activity_type"]),
                "clip_filename":     row["clip_filename"] if row["clip_filename"] else "",
            }
            for row in rows
        ]

        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/alerts/snapshot/<path:filename>')
def alert_snapshot(filename):
    """
    Serves alert snapshot JPEG images from the ALERTS_PATH folder.
    React fetches these for the thumbnail cards and the dialog image.
    Security: os.path.basename() strips any path traversal attempts.
    """
    safe_name = os.path.basename(filename)   # strips ../../ etc.
    if not os.path.exists(os.path.join(ALERTS_PATH, safe_name)):
        return "Snapshot not found", 404

    return send_from_directory(ALERTS_PATH, safe_name, mimetype='image/jpeg')




@app.route('/api/alerts/clip/<path:filename>')
def alert_clip(filename):
    """
    Serves the short alert clip MP4 (20s) from ALERTS_PATH.
    Supports Range requests so the browser video player can seek.
    """
    safe_name = os.path.basename(filename)
    fpath     = os.path.join(ALERTS_PATH, safe_name)
    if not os.path.exists(fpath):
        return "Clip not found", 404

    file_size = os.path.getsize(fpath)
    range_hdr = request.headers.get('Range')

    if range_hdr:
        b_start, b_end = 0, file_size - 1
        parts = range_hdr.replace('bytes=', '').split('-')
        if parts[0]: b_start = int(parts[0])
        if len(parts) > 1 and parts[1]: b_end = int(parts[1])
        length = b_end - b_start + 1

        def gen_clip_range():
            with open(fpath, 'rb') as f:
                f.seek(b_start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(64 * 1024, remaining))
                    if not chunk: break
                    yield chunk
                    remaining -= len(chunk)

        return Response(gen_clip_range(), status=206, mimetype='video/mp4', headers={
            'Content-Range':  f'bytes {b_start}-{b_end}/{file_size}',
            'Content-Length': str(length),
            'Accept-Ranges':  'bytes',
        })

    def gen_clip_full():
        with open(fpath, 'rb') as f:
            while chunk := f.read(64 * 1024):
                yield chunk

    return Response(gen_clip_full(), mimetype='video/mp4', headers={
        'Content-Length': str(file_size),
        'Accept-Ranges':  'bytes',
    })


@app.route('/api/storage')
def storage_status():
    """
    Returns disk usage stats for the SSD partition.
    Called by the React recordings page every 30 seconds to show
    the Storage Status indicator without hammering the Pi.
    """
    try:
        total, used, free = shutil.disk_usage(SSD_PATH)
        percent_used = (used / total) * 100

        def fmt_gb(b):
            return round(b / (1024 ** 3), 2)

        return jsonify({
            "total_gb":    fmt_gb(total),
            "used_gb":     fmt_gb(used),
            "free_gb":     fmt_gb(free),
            "percent_used": round(percent_used, 1),
            # health: green < 70%, yellow 70-89%, red >= 90%
            "health": "critical" if percent_used >= 90
                      else "warning" if percent_used >= 70
                      else "ok",
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/recordings')
def list_recordings():
    if not os.path.exists(SSD_PATH):
        return jsonify([])

    current_file     = recorder.get_current_file()
    current_filename = os.path.basename(current_file) if current_file else None
    result = []

    for filename in sorted(os.listdir(SSD_PATH), reverse=True):
        if not filename.endswith(".mp4"):
            continue
        fpath   = os.path.join(SSD_PATH, filename)
        stats   = os.stat(fpath)
        is_live = (filename == current_filename)

        if is_live:
            elapsed = int(time.time() - recorder.start_time)
            h, m, s = elapsed // 3600, (elapsed % 3600) // 60, elapsed % 60
            duration = f"{h:02d}:{m:02d}:{s:02d} (Recording...)"
        else:
            duration = "Completed"

        result.append({
            "id":       filename,
            "filename": filename,
            "date":     time.strftime('%b %d, %Y %H:%M', time.localtime(stats.st_ctime)),
            "camera":   "Camera 01 - Main Entrance",
            "size":     f"{round(stats.st_size / 1048576, 2)} MB",
            "duration": duration,
            "status":   "recording" if is_live else "completed",
        })

    return jsonify(result)


@app.route('/api/video/stream')
def stream_file():
    filename = os.path.basename(request.args.get('file', ''))
    if not filename:
        return "File not specified", 400

    fpath = os.path.join(SSD_PATH, filename)
    if not os.path.exists(fpath):
        return "File not found", 404

    file_size = os.path.getsize(fpath)
    range_hdr = request.headers.get('Range')

    if range_hdr:
        b_start, b_end = 0, file_size - 1
        parts = range_hdr.replace('bytes=', '').split('-')
        if parts[0]: b_start = int(parts[0])
        if len(parts) > 1 and parts[1]: b_end = int(parts[1])
        length = b_end - b_start + 1

        def gen_range():
            with open(fpath, 'rb') as f:
                f.seek(b_start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(64 * 1024, remaining))
                    if not chunk:
                        break
                    yield chunk
                    remaining -= len(chunk)

        return Response(gen_range(), status=206, mimetype='video/mp4', headers={
            'Content-Range':  f'bytes {b_start}-{b_end}/{file_size}',
            'Content-Length': str(length),
            'Accept-Ranges':  'bytes',
        })

    def gen_full():
        with open(fpath, 'rb') as f:
            while chunk := f.read(64 * 1024):
                yield chunk

    return Response(gen_full(), mimetype='video/mp4', headers={
        'Content-Length': str(file_size),
        'Accept-Ranges':  'bytes',
    })


@app.route('/snapshot')
def snapshot():
    """
    Serve the latest JPEG snapshot written by SnapshotWriter.
    The React frontend polls this every 200ms for the live feed.
    """
    if os.path.exists(SNAPSHOT_PATH):
        return send_from_directory(
            os.path.dirname(SNAPSHOT_PATH),
            os.path.basename(SNAPSHOT_PATH),
            mimetype='image/jpeg',
        )

    # Camera not ready yet ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬ return a black placeholder frame
    blank = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
    cv2.putText(blank, "Camera initializing...", (120, HEIGHT // 2),
                cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
    _, buf = cv2.imencode('.jpg', blank)
    return Response(buf.tobytes(), mimetype='image/jpeg', headers={
        'Cache-Control': 'no-store, no-cache, must-revalidate, max-age=0',
    })


# ---------------------------------------------------------------------------
# 8. GRACEFUL SHUTDOWN
# ---------------------------------------------------------------------------
def cleanup():
    print("\nShutting down gracefully...")
    recorder.finalize()
    recorder._cleanup_clips()   # delete clips â†’ next boot uses offset on completed recording
    try:
        picam2.stop()
    except Exception:
        pass
    print("Shutdown complete.")

atexit.register(cleanup)

def _sig(sig, frame):
    cleanup()
    sys.exit(0)

signal.signal(signal.SIGTERM, _sig)
signal.signal(signal.SIGINT,  _sig)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, threaded=True)
