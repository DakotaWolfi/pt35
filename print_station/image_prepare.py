"""Bounded server-side receipt image conversion using Pillow.

Source photos may be large. A size-limited monochrome receipt PNG is
returned to the browser or stored with the receipt.
"""
import base64
import io
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_UPLOAD=12*1024*1024
MAX_PIXELS=32_000_000
MAX_PRINT_HEIGHT=1024
MAX_PNG=32*1024

def prepare_receipt_image(raw, brightness=25, width=384):
    """Brightness 0..70; 25 is a deliberately lighter thermal-photo default."""
    if type(width) is not int or not 128 <= width <= 576 or width % 8:
        raise ValueError("Image width must be 128..576 dots in steps of 8")
    if type(brightness) is not int or not 0 <= brightness <= 70:
        raise ValueError("Brightness must be between 0 and 70")
    if not isinstance(raw,(bytes,bytearray)) or not 0<len(raw)<=MAX_UPLOAD:
        raise ValueError("Source image exceeds 12 MiB upload limit")
    try:
        with Image.open(io.BytesIO(raw)) as im:
            if im.width<1 or im.height<1 or im.width*im.height>MAX_PIXELS:
                raise ValueError("Image dimensions exceed 32 megapixels")
            if im.format not in ("PNG","JPEG","WEBP","BMP","GIF","TIFF"):
                raise ValueError("Unsupported image type")
            source_width,source_height=im.size
            if im.format=="JPEG":
                im.draft("RGB",(width,MAX_PRINT_HEIGHT))
            im.seek(0)  # first page/frame for GIF and TIFF
            source=ImageOps.exif_transpose(im)
            source.thumbnail((width,MAX_PRINT_HEIGHT),Image.Resampling.LANCZOS)
            rgba=source.convert("RGBA")
            background=Image.new("RGBA",rgba.size,"white")
            background.alpha_composite(rgba)
            gray=ImageOps.autocontrast(ImageOps.grayscale(background.convert("RGB")),cutoff=1)
            # Raise midtones for thermal paper; otherwise Floyd-Steinberg
            # places too many black dots in faces and shaded photos.
            gamma=1.0-(brightness/100.0)
            lut=[min(255,round(255*((v/255)**gamma))) for v in range(256)]
            gray=gray.point(lut)
            # Error-diffusion dithering preserves gradients, text, and
            # photographic details without needing a large PNG payload.
            bw=gray.convert("1",dither=Image.Dither.FLOYDSTEINBERG)
            out=io.BytesIO()
            bw.save(out,format="PNG",optimize=True)
            png=out.getvalue()
            if len(png)>MAX_PNG:
                # Complex noisy photos may exceed the compressed PNG budget.
                # Downscale proportionally only when necessary.
                bw.thumbnail((max(1,bw.width//2),max(1,bw.height//2)),Image.Resampling.NEAREST)
                out=io.BytesIO()
                bw.save(out,format="PNG",optimize=True)
                png=out.getvalue()
            if len(png)>MAX_PNG:
                raise ValueError("Image cannot be compressed for receipt")
            return {"image":base64.b64encode(png).decode("ascii"),
                    "width":bw.width,"height":bw.height,
                    "source_width":source_width,"source_height":source_height,
                    "bytes":len(png)}
    except (OSError,UnidentifiedImageError,Image.DecompressionBombError) as exc:
        raise ValueError("Cannot decode this image") from exc
