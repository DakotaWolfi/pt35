import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app

class TestAdminTransport(unittest.TestCase):
    def setUp(self):
        self.old_conf = app.Handler.conf
        self.conf = dict(app.DEFAULT)
        self.conf.update({"access_mode":"both", "admin_token":"secret-test-token", "require_https_proxy":False})
        app.Handler.conf = self.conf
        class Secure(app.Handler):
            admin_listener = True
        Secure.conf=self.conf
        self.http = ThreadingHTTPServer(("127.0.0.1",0), app.Handler)
        self.secure = ThreadingHTTPServer(("127.0.0.1",0), Secure)
        self.threads=[]
        for server in (self.http, self.secure):
            thread=threading.Thread(target=server.serve_forever,daemon=True)
            thread.start()
            self.threads.append(thread)

    def tearDown(self):
        for server in (self.http,self.secure):
            server.shutdown()
            server.server_close()
        app.Handler.conf = self.old_conf

    def request(self, server, path, forwarded=None):
        headers={"X-FMI-Admin":"secret-test-token"}
        if forwarded is not None: headers["X-Forwarded-Proto"]=forwarded
        req=urllib.request.Request("http://127.0.0.1:{}/{}".format(server.server_port,path),headers=headers)
        try:
            with urllib.request.urlopen(req,timeout=2) as r:
                return r.status
        except urllib.error.HTTPError as exc:
            return exc.code

    def test_browser_image_sources_allowed(self):
        import http.client
        conn=http.client.HTTPConnection("127.0.0.1",self.http.server_port,timeout=2)
        try:
            conn.request("GET","/")
            response=conn.getresponse()
            self.assertEqual(response.status,200)
            policy=response.getheader("Content-Security-Policy")
            self.assertIn("img-src 'self' blob: data:",policy)
            response.read()
        finally:
            conn.close()

    def test_http_does_not_expose_admin_even_with_spoofed_headers(self):
        for path in ("api/settings","api/history","api/history/1"):
            self.assertEqual(self.request(self.http,path,forwarded="https"),403)
        self.assertEqual(self.request(self.http,"api/status"),200)

    def test_admin_listener_needs_https_proxy_indication(self):
        self.assertEqual(self.request(self.secure,"api/settings"),403)
        self.assertEqual(self.request(self.secure,"api/settings",forwarded="https"),200)

if __name__=="__main__":
    unittest.main()
