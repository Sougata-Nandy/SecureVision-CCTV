# centroid_tracker.py
# Place this file in the same folder as app.py
# This file is ONLY imported by app.py — you never run it directly.
#
# HOW IT WORKS:
#   - Every frame, YOLO gives us bounding boxes of detected persons
#   - This tracker converts each box into a "centroid" (center point x, y)
#   - It then matches new centroids to existing ones by proximity
#   - Each person gets a unique ID that persists across frames
#   - If a person disappears for too many frames → their ID is removed

import numpy as np
from collections import OrderedDict


class CentroidTracker:
    def __init__(self, max_disappeared=20):
        """
        max_disappeared: how many consecutive frames a person can be
                         missing before we stop tracking them.
                         At 20 FPS, 20 frames = ~1 second grace period.
        """
        self.next_object_id = 0

        # Stores: { person_id: centroid (x, y) }
        self.objects = OrderedDict()

        # Stores: { person_id: bounding_box (x1, y1, x2, y2) }
        self.bboxes = OrderedDict()

        # Stores: { person_id: how many frames they have been missing }
        self.disappeared = OrderedDict()

        self.max_disappeared = max_disappeared

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _register(self, centroid, bbox):
        """Assign a brand-new ID to a newly seen person."""
        self.objects[self.next_object_id]    = centroid
        self.bboxes[self.next_object_id]     = bbox
        self.disappeared[self.next_object_id] = 0
        self.next_object_id += 1

    def _deregister(self, object_id):
        """Remove a person who has been missing too long."""
        del self.objects[object_id]
        del self.bboxes[object_id]
        del self.disappeared[object_id]

    # ------------------------------------------------------------------
    # Main method — call this every frame with the list of YOLO boxes
    # ------------------------------------------------------------------

    def update(self, rects):
        """
        rects: list of tuples (x1, y1, x2, y2) — one per detected person.
               Pass an empty list [] if no persons are detected.

        Returns:
            objects  -> { id: centroid (x, y) }
            bboxes   -> { id: (x1, y1, x2, y2) }
        """

        # ── CASE 1: No detections this frame ──────────────────────────
        if len(rects) == 0:
            for object_id in list(self.disappeared.keys()):
                self.disappeared[object_id] += 1
                if self.disappeared[object_id] > self.max_disappeared:
                    self._deregister(object_id)
            return self.objects, self.bboxes

        # ── Compute centroids for all detected boxes ───────────────────
        input_centroids = []
        for (x1, y1, x2, y2) in rects:
            cx = int((x1 + x2) / 2.0)
            cy = int((y1 + y2) / 2.0)
            input_centroids.append((cx, cy))
        input_centroids = np.array(input_centroids)

        # ── CASE 2: No existing tracked persons → register all as new ──
        if len(self.objects) == 0:
            for i, centroid in enumerate(input_centroids):
                self._register(centroid, rects[i])

        # ── CASE 3: Match new detections to existing tracked persons ───
        else:
            object_ids       = list(self.objects.keys())
            object_centroids = np.array(list(self.objects.values()))

            # Euclidean distance matrix: existing × new
            # Shape: (num_existing, num_new)
            D = np.linalg.norm(
                object_centroids[:, np.newaxis] - input_centroids[np.newaxis, :],
                axis=2
            )

            # Sort existing by their closest new detection
            rows = D.min(axis=1).argsort()
            cols = D.argmin(axis=1)[rows]

            used_rows = set()
            used_cols = set()

            for (row, col) in zip(rows, cols):
                if row in used_rows or col in used_cols:
                    continue  # already matched

                object_id = object_ids[row]
                self.objects[object_id]    = input_centroids[col]
                self.bboxes[object_id]     = rects[col]
                self.disappeared[object_id] = 0

                used_rows.add(row)
                used_cols.add(col)

            unused_rows = set(range(D.shape[0])) - used_rows
            unused_cols = set(range(D.shape[1])) - used_cols

            # Existing persons with no matching new detection → increment disappeared
            if D.shape[0] >= D.shape[1]:
                for row in unused_rows:
                    object_id = object_ids[row]
                    self.disappeared[object_id] += 1
                    if self.disappeared[object_id] > self.max_disappeared:
                        self._deregister(object_id)

            # New detections with no matching existing person → register as new
            else:
                for col in unused_cols:
                    self._register(input_centroids[col], rects[col])

        return self.objects, self.bboxes
