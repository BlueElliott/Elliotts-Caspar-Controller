"""CasparCG AMCP TCP client."""
import socket
import time


class AMCPClient:
    def __init__(self, host: str = "127.0.0.1", port: int = 5250, timeout: float = 1.5):
        self.host = host
        self.port = port
        self.timeout = timeout

    def send(self, command: str) -> str:
        try:
            with socket.create_connection((self.host, self.port), timeout=self.timeout) as sock:
                sock.sendall((command + "\r\n").encode())
                time.sleep(0.05)
                response = b""
                sock.settimeout(0.5)
                try:
                    while True:
                        chunk = sock.recv(4096)
                        if not chunk:
                            break
                        response += chunk
                except socket.timeout:
                    pass
                return response.decode(errors="replace").strip()
        except Exception as e:
            return f"ERROR: {e}"

    def ping(self) -> bool:
        response = self.send("VERSION")
        return response.startswith("201")

    def info_layer(self, channel: int = 1, layer: int = 1) -> str:
        return self.send(f"INFO {channel}-{layer}")

    def play_html(self, channel: int, url: str) -> str:
        return self.send(f'PLAY {channel}-1 [HTML] "{url}"')

    def stop_channel(self, channel: int) -> str:
        return self.send(f"STOP {channel}-1")

    def info_channel(self, channel: int) -> str:
        return self.send(f"INFO {channel}")
