import http.server
import functools

class CORSHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

if __name__ == "__main__":
    handler = functools.partial(CORSHandler, directory=r"C:\Users\taha\Downloads\backtester_signal_engine_autoaccept\scratch")
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 8934), handler)
    server.serve_forever()
