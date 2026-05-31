import cv2
import os

VIDEO_FILE    = "training_normal.mp4"
OUTPUT_FOLDER = "training_frames"
IMG_SIZE      = 64       # resize every frame to 64x64
SAMPLE_EVERY  = 40       # take 1 frame every 40 frames (saves disk space)

os.makedirs(OUTPUT_FOLDER, exist_ok=True)

cap   = cv2.VideoCapture(VIDEO_FILE)
count = 0
saved = 0

while True:
    ret, frame = cap.read()
    if not ret:
        break
    if count % SAMPLE_EVERY == 0:
        frame_small = cv2.resize(frame, (IMG_SIZE, IMG_SIZE))
        cv2.imwrite(f"{OUTPUT_FOLDER}/frame_{saved:06d}.jpg", frame_small)
        saved += 1
    count += 1

cap.release()
print(f"Done! Extracted {saved} frames into '{OUTPUT_FOLDER}/' folder")
