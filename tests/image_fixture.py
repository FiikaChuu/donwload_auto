from io import BytesIO

from PIL import Image


def jpeg_bytes():
    buffer = BytesIO()
    Image.new("RGB", (24, 24), (50, 100, 150)).save(buffer, format="JPEG")
    return buffer.getvalue()
