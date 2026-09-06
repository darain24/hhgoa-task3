"""Local face presence detection only; no recognition or embeddings."""

import argparse
import hashlib
import os
import sys
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError
from requests import RequestException


class FaceNotDetectedError(Exception):
    """The input could not be processed as a single-face image."""


def detect_face(image_path: str) -> dict[str, Any]:
    """Return RetinaFace confidence, area and image digest; raise FaceNotDetectedError."""
    try:
        raw = Path(image_path).read_bytes()
        with Image.open(BytesIO(raw)) as image:
            image.verify()
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
        raise FaceNotDetectedError("Provide a readable, valid local image.") from None

    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
    try:
        import cv2
        import numpy as np
        from deepface import DeepFace

        pixels = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
        if pixels is None:
            raise FaceNotDetectedError("Image format cannot be decoded.")
        faces = DeepFace.extract_faces(
            img_path=pixels,
            detector_backend="retinaface",
            enforce_detection=True,
            align=False,
        )
    except ImportError:
        raise FaceNotDetectedError(
            "Install requirements.txt with Python 3.12 first."
        ) from None
    except ValueError:
        raise FaceNotDetectedError(
            "No face detected, or detector could not process image."
        ) from None
    except (OSError, RequestException):
        raise FaceNotDetectedError(
            "Could not load RetinaFace weights; check network and disk."
        ) from None
    if len(faces) != 1:
        raise FaceNotDetectedError(
            "Provide an image containing exactly one clear face."
        )
    face = faces[0]
    return {
        "confidence": float(face["confidence"]),
        "facial_area": {
            key: int(face["facial_area"][key]) for key in ("x", "y", "w", "h")
        },
        "detector": "RetinaFace",
        "source_image_sha256": hashlib.sha256(raw).hexdigest(),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", nargs="?", default="test_images/sample_face.jpg")
    try:
        result = detect_face(parser.parse_args().image)
        print(f"Face detected — confidence: {result['confidence']:.4f}")
        print(f"Facial area: {result['facial_area']}")
    except FaceNotDetectedError as error:
        print(f"Error [face]: {error}", file=sys.stderr)
        sys.exit(1)
