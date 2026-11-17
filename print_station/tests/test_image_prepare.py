"""Large-source receipt photo conversion, no actual printer hardware."""
import io
import unittest
from PIL import Image
from image_prepare import prepare_receipt_image,MAX_UPLOAD

class PrepareReceiptImageTests(unittest.TestCase):
    def test_large_color_source_is_dithered_small_png(self):
        gray=Image.linear_gradient("L").resize((2048,1536))
        im=Image.merge("RGB",(gray,gray,gray))
        data=io.BytesIO()
        im.save(data,format="JPEG",quality=92)
        result=prepare_receipt_image(data.getvalue())
        self.assertLessEqual(result["width"],384)
        self.assertLessEqual(result["height"],240)
        self.assertLessEqual(result["bytes"],32*1024)
        import base64
        with Image.open(io.BytesIO(base64.b64decode(result["image"]))) as printed:
            self.assertEqual(printed.format,"PNG")
            self.assertEqual(printed.mode,"1")
            self.assertLessEqual(printed.width,384)

    def test_nonimage_rejected(self):
        with self.assertRaises(ValueError):
            prepare_receipt_image(b"not an image")

    def test_huge_source_bytes_rejected(self):
        with self.assertRaises(ValueError):
            prepare_receipt_image(b"x"*(MAX_UPLOAD+1))

    def test_source_pixel_budget_rejected(self):
        im=Image.new("1",(6000,6000))
        out=io.BytesIO()
        im.save(out,format="PNG")
        with self.assertRaises(ValueError):
            prepare_receipt_image(out.getvalue())

if __name__=="__main__":unittest.main()
