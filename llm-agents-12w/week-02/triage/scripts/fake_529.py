"""Local stand-in for an overloaded Claude API: answers every POST with HTTP 529.
Goes in triage/scripts/. Run: python scripts/fake_529.py   (leave it running)"""
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

T0 = time.perf_counter()

class Overloaded(BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers.get("content-length", 0)))   # drain the request body
        body = b'{"type":"error","error":{"type":"overloaded_error","message":"Overloaded"}}'
        self.send_response(529)                                       # what the real API sends when busy
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        print(f"hit at t={time.perf_counter() - T0:6.2f}s  {self.path}", flush=True)

    def log_message(self, *args):                                     # silence default access log
        pass

print("fake API on http://127.0.0.1:8529 (always 529)", flush=True)
HTTPServer(("127.0.0.1", 8529), Overloaded).serve_forever()
