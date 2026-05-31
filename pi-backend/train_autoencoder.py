import numpy as np
import os
import cv2
import tensorflow as tf
from tensorflow import keras
from tensorflow.keras import layers

FRAMES_FOLDER  = "training_frames"
IMG_SIZE       = 64
EPOCHS         = 30
BATCH_SIZE     = 32

# ── 1. Load frames ─────────────────────────────────────────────────────────
print("Loading frames...")
frames = []
for fname in sorted(os.listdir(FRAMES_FOLDER)):
    if fname.endswith(".jpg"):
        img = cv2.imread(os.path.join(FRAMES_FOLDER, fname))
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        frames.append(img)

X = np.array(frames, dtype="float32") / 255.0
print(f"Loaded {len(X)} frames — shape: {X.shape}")

# ── 2. Build Autoencoder ───────────────────────────────────────────────────
inp = keras.Input(shape=(IMG_SIZE, IMG_SIZE, 3))

# Encoder
x = layers.Conv2D(32, 3, activation="relu", padding="same")(inp)
x = layers.MaxPooling2D(2)(x)
x = layers.Conv2D(16, 3, activation="relu", padding="same")(x)
x = layers.MaxPooling2D(2)(x)
x = layers.Conv2D(8,  3, activation="relu", padding="same")(x)
encoded = layers.MaxPooling2D(2)(x)

# Decoder
x = layers.Conv2D(8,  3, activation="relu", padding="same")(encoded)
x = layers.UpSampling2D(2)(x)
x = layers.Conv2D(16, 3, activation="relu", padding="same")(x)
x = layers.UpSampling2D(2)(x)
x = layers.Conv2D(32, 3, activation="relu", padding="same")(x)
x = layers.UpSampling2D(2)(x)
decoded = layers.Conv2D(3, 3, activation="sigmoid", padding="same")(x)

autoencoder = keras.Model(inp, decoded)
autoencoder.compile(optimizer="adam", loss="mse")
print("Model built!")

# ── 3. Train ───────────────────────────────────────────────────────────────
print("\nTraining started... (takes 10-20 minutes)")
autoencoder.fit(
    X, X,
    epochs=EPOCHS,
    batch_size=BATCH_SIZE,
    shuffle=True,
    validation_split=0.1,
    verbose=1
)

# ── 4. Calculate threshold ─────────────────────────────────────────────────
print("\nCalculating MSE threshold...")
reconstructed = autoencoder.predict(X, verbose=0)
mse_values    = np.mean(np.square(X - reconstructed), axis=(1, 2, 3))
threshold     = float(np.percentile(mse_values, 95))

print(f"\n  Normal MSE average : {np.mean(mse_values):.6f}")
print(f"  Threshold (95th %) : {threshold:.6f}  ← this is your threshold")
print(f"  Normal MSE max     : {np.max(mse_values):.6f}")

# ── 5. Save ────────────────────────────────────────────────────────────────
autoencoder.save("autoencoder.h5")
np.save("mse_threshold.npy", np.array([threshold]))
print("\nSaved: autoencoder.h5")
print("Saved: mse_threshold.npy")
print("\nStep 3 Done! Tell me and I will give you Step 4.")
