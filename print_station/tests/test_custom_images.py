import base64
import io
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
import app

def png_data():
    image=Image.new("RGB",(8,8),"white")
    image.putpixel((2,3),(0,0,0))
    stream=io.BytesIO()
    image.save(stream,format="PNG")
    return base64.b64encode(stream.getvalue()).decode("ascii")

class TestCustomReceiptImages(unittest.TestCase):
    def test_image_embedded_at_correct_position(self):
        receipt=app.validate_custom({
            "title":"T","lines":[
              {"type":"text","text":"BEFORE"},
              {"type":"image","image":png_data()},
              {"type":"text","text":"AFTER"}]
        },app.DEFAULT)
        out=app.make_custom_receipt(receipt,app.DEFAULT)
        pos_a=out.find(b"BEFORE")
        pos_img=out.find(bytes([29,118,48,0]))
        pos_b=out.find(b"AFTER")
        self.assertTrue(0<=pos_a<pos_img<pos_b)
        self.assertEqual(out[pos_img+4:pos_img+8],bytes([1,0,8,0]))
        self.assertIn(bytes([27,97,0]),out)

    def test_reject_bad_or_oversize_png(self):
        with self.assertRaises(ValueError):
            app.validate_custom({"title":"T","lines":[{"type":"image","image":"AAAA"}]},app.DEFAULT)
        im=Image.new("RGB",(385,8),"white")
        f=io.BytesIO(); im.save(f,format="PNG")
        encoded=base64.b64encode(f.getvalue()).decode("ascii")
        with self.assertRaises(ValueError):
            app.validate_custom({"title":"T","lines":[{"type":"image","image":encoded}]},app.DEFAULT)

    def test_25_images_allowed_when_configured(self):
        conf={**app.DEFAULT,"max_images_per_receipt":25}
        rows=[{"type":"image","image":png_data()} for _ in range(25)]
        receipt=app.validate_custom({"title":"25 pictures","lines":rows},conf)
        self.assertEqual(len(receipt["lines"]),25)

    def test_limit_image_count(self):
        with self.assertRaises(ValueError):
            app.validate_custom({"title":"T","lines":[{"type":"image","image":png_data()}]*3},app.DEFAULT)

if __name__=="__main__":
    unittest.main()
