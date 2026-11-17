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
        self.assertLessEqual(result["height"],1024)
        self.assertLessEqual(result["bytes"],32*1024)
        import base64
        with Image.open(io.BytesIO(base64.b64decode(result["image"]))) as printed:
            self.assertEqual(printed.format,"PNG")
            self.assertEqual(printed.mode,"1")
            self.assertLessEqual(printed.width,384)

    def test_brightness_reduces_black_dot_coverage(self):
        import base64
        gradient=Image.linear_gradient("L").resize((256,128))
        original=io.BytesIO()
        gradient.save(original,format="PNG")
        dark=prepare_receipt_image(original.getvalue(),brightness=0)
        light=prepare_receipt_image(original.getvalue(),brightness=60)
        def black_dots(item):
            with Image.open(io.BytesIO(base64.b64decode(item["image"]))) as im:
                return sum(1 for v in im.getdata() if v==0)
        self.assertLess(black_dots(light),black_dots(dark))

    def test_custom_print_width(self):
        picture=Image.new("RGB",(800,160),(110,120,130))
        output=io.BytesIO()
        picture.save(output,"PNG")
        result=prepare_receipt_image(output.getvalue(),width=576)
        self.assertEqual(result["width"],576)
        self.assertLessEqual(result["height"],240)

    def test_3_to_2_photo_reaches_configured_width(self):
        picture=Image.new("RGB",(1500,1000),(110,120,130))
        output=io.BytesIO()
        picture.save(output,"PNG")
        result=prepare_receipt_image(output.getvalue(),width=512)
        self.assertEqual(result["width"],512)
        self.assertEqual(result["height"],341)

    def test_portrait_photo_can_be_taller_than_240_dots(self):
        picture=Image.new("RGB",(800,1200),(110,120,130))
        output=io.BytesIO()
        picture.save(output,"PNG")
        result=prepare_receipt_image(output.getvalue(),width=512)
        self.assertEqual(result["width"],512)
        self.assertEqual(result["height"],768)

    def test_invalid_width_rejected(self):
        with self.assertRaises(ValueError):
            prepare_receipt_image(b"image",width=577)

    def test_invalid_brightness_rejected(self):
        with self.assertRaises(ValueError):
            prepare_receipt_image(b"image",brightness=99)

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
