"""Ein Poly Haven ohne Netz: feste Antworten für die Tests."""
import io
import json

from PIL import Image

API = "https://api.polyhaven.com"


def png(color, size=(64, 64)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def panorama() -> bytes:
    """2:1-Rundum-Bild: oben weiß, unten schwarz, Mitte (Blick +X) rot, links davon (+Y) grün."""
    w, h = 256, 128
    img = Image.new("RGB", (w, h), (40, 40, 40))
    px = img.load()
    for y in range(h):
        for x in range(w):
            u, v = (x + 0.5) / w, (y + 0.5) / h
            if v < 0.15:
                px[x, y] = (255, 255, 255)
            elif v > 0.85:
                px[x, y] = (0, 0, 0)
            elif 0.45 < u < 0.55:
                px[x, y] = (255, 0, 0)
            elif 0.2 < u < 0.3:
                px[x, y] = (0, 255, 0)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=95)
    return buf.getvalue()


def responses() -> dict[str, bytes]:
    tex = {"red_brick_03": {"name": "Red Brick 03", "categories": ["brick", "wall"], "tags": ["red"],
                            "thumbnail_url": "https://cdn.polyhaven.com/thumb/red_brick_03.png",
                            "authors": {"Rob Tuytel": "All"}},
           "rocky_ground": {"name": "Rocky Ground", "categories": ["rock", "floor"], "tags": [],
                            "thumbnail_url": "https://cdn.polyhaven.com/thumb/rocky_ground.png"}}
    hdris = {"moonless_golf": {"name": "Moonless Golf", "categories": ["night", "skies"], "tags": ["dark"],
                               "thumbnail_url": "https://cdn.polyhaven.com/thumb/moonless_golf.png"}}
    files = {"Diffuse": {"1k": {"jpg": {"url": "https://dl.polyhaven.org/red_brick_03_diff_1k.jpg"}}},
             "nor_dx": {"1k": {"jpg": {"url": "https://dl.polyhaven.org/red_brick_03_nor_dx_1k.jpg"}}},
             "Rough": {"1k": {"jpg": {"url": "https://dl.polyhaven.org/red_brick_03_rough_1k.jpg"}}}}
    sky_files = {"hdri": {"1k": {"hdr": {"url": "https://dl.polyhaven.org/moonless_golf_1k.hdr"}}},
                 "tonemapped": {"url": "https://dl.polyhaven.org/moonless_golf.jpg"}}
    return {
        f"{API}/assets?type=textures": json.dumps(tex).encode(),
        f"{API}/assets?type=hdris": json.dumps(hdris).encode(),
        f"{API}/categories/textures": json.dumps({"all": 2, "rock": 1, "brick": 1, "wall": 1}).encode(),
        f"{API}/categories/hdris": json.dumps({"all": 1, "night": 1, "skies": 1}).encode(),
        f"{API}/files/red_brick_03": json.dumps(files).encode(),
        f"{API}/files/moonless_golf": json.dumps(sky_files).encode(),
        "https://cdn.polyhaven.com/thumb/red_brick_03.png": png((180, 60, 40)),
        "https://cdn.polyhaven.com/thumb/rocky_ground.png": png((120, 120, 110)),
        "https://cdn.polyhaven.com/thumb/moonless_golf.png": png((10, 10, 30)),
        "https://dl.polyhaven.org/red_brick_03_diff_1k.jpg": png((180, 60, 40), (128, 128)),
        "https://dl.polyhaven.org/red_brick_03_nor_dx_1k.jpg": png((128, 128, 255), (128, 128)),
        "https://dl.polyhaven.org/moonless_golf.jpg": panorama(),
    }


class FakeNet:
    def __init__(self) -> None:
        self.data = responses()
        self.calls: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.calls.append(url)
        if url not in self.data:
            raise OSError(f"404 {url}")
        return self.data[url]
