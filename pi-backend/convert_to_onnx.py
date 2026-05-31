# convert_to_onnx.py  — run on LAPTOP
import tensorflow as tf
import tf2onnx
import numpy as np

model = tf.keras.models.load_model("autoencoder.h5", compile=False)

spec = (tf.TensorSpec((None, 64, 64, 3), tf.float32, name="input"),)
model_proto, _ = tf2onnx.convert.from_keras(model, input_signature=spec, opset=13)

with open("autoencoder.onnx", "wb") as f:
    f.write(model_proto.SerializeToString())

print("Done! autoencoder.onnx created")
