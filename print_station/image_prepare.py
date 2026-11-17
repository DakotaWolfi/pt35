"""Bounded server-side receipt image conversion using Pillow.

Source photos may be large. Only a small, monochrome 384x240 PNG is
returned to the browser or stored with the receipt.
"""
import base64
import io
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_UPLOAD=12*1024*1024
MAX_PIXELS=32_000_000
TARGET=(384,240)
MAX_PNG=32*1024

def prepare_receipt_image(raw):
    if not isinstance(raw,(bytes,bytearray)) or not 0<len(raw)<=MAX_UPLOAD:
        raise ValueError("Source image exceeds 12 MiB upload limit")
    try:
        with Image.open(io.BytesIO(raw)) as im:
            if im.width<1 or im.height<1 or im.width*im.height>MAX_PIXELS:
                raise ValueError("Image dimensions exceed 32 megapixels")
            if im.format not in ("PNG","JPEG","WEBP","BMP","GIF","TIFF"):
                raise ValueError("Unsupported image type")
            if im.format=="JPEG":
                im.draft("RGB",TARGET)
            im.seek(0)  # first page/frame for GIF and TIFF
            source=ImageOps.exif_transpose(im)
            source.thumbnail(TARGET,Image.Resampling.LANCZOS)
            rgba=source.convert("RGBA")
            background=Image.new("RGBA",rgba.size,"white")
            background.alpha_composite(rgba)
            gray=ImageOps.autocontrast(ImageOps.grayscale(background.convert("RGB")))
            # Error-diffusion dithering preserves gradients, text, and
            # photographic details without needing a large PNG payload.
            bw=gray.convert("1",dither=Image.Dither.FLOYDSTEINBERG)
            out=io.BytesIO()
            bw.save(out,format="PNG",optimize=True)
            png=out.getvalue()
            if len(png)>MAX_PNG:
                # Should be unusual at <=384x240 1-bit; retry at half-size.
                bw.thumbnail((192,120),Image.Resampling.NEAREST)
                out=io.BytesIO()
                bw.save(out,format="PNG",optimize=True)
                png=out.getvalue()
            if len(png)>MAX_PNG:
                raise ValueError("Image cannot be compressed for receipt")
            return {"image":base64.b64encode(png).decode("ascii"),
                    "width":bw.width,"height":bw.height,
                    "source_width":im.width,"source_height":im.height,
                    "bytes":len(png)}
    except (OSError,UnidentifiedImageError,Image.DecompressionBombError) as exc:
        raise ValueError("Cannot decode this image") from exc
