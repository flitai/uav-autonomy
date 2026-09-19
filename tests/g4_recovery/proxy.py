"""Owned, bounded observation fault proxy; never forwards client business data."""
import select
import socket
import threading
import time


class ObserverProxy:
    def __init__(self, port, upstream):
        self.upstream, self.port = upstream, port
        self.listener = socket.socket()
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        self.listener.bind(('127.0.0.1', port)); self.listener.listen(4); self.listener.settimeout(.2)
        self.lock = threading.Lock()
        self.blocked, self.partial, self.stopping = False, False, False
        self.pair, self.error = None, None
        self.connections, self.bytes, self.partial_bytes = 0, 0, 0
        self.thread = threading.Thread(target=self.work, daemon=True); self.thread.start()

    def cut(self, partial=False):
        with self.lock:
            if partial:
                self.partial = True
            else:
                self.blocked = True
                if self.pair:
                    for stream in self.pair:
                        try: stream.shutdown(socket.SHUT_RDWR)
                        except OSError: pass

    def restore(self):
        with self.lock:
            self.partial, self.blocked = False, False

    def work(self):
        try:
            while not self.stopping:
                try: client, _ = self.listener.accept()
                except socket.timeout: continue
                except OSError:
                    if self.stopping: break
                    raise
                with client:
                    if self.blocked: continue
                    try:
                        with socket.create_connection(('127.0.0.1', self.upstream), timeout=3) as backend:
                            client.settimeout(1); backend.settimeout(1)
                            self.pair = (client, backend); self.connections += 1
                            while not self.stopping and not self.blocked:
                                readable, _, _ = select.select([client, backend], [], [], .2)
                                if client in readable:
                                    if client.recv(4096): raise ValueError('Observer sent backend business data')
                                    break
                                if backend in readable:
                                    data = backend.recv(65536)
                                    if not data: break
                                    if self.partial:
                                        client.sendall(data[:7]); self.partial_bytes += min(7, len(data))
                                        self.blocked = True; self.partial = False; break
                                    client.sendall(data); self.bytes += len(data)
                    except OSError:
                        pass  # Fault teardown intentionally interrupts these owned sockets.
                    finally:
                        self.pair = None
        except Exception as error:
            self.error = repr(error)

    def close(self):
        self.stopping = True; self.cut(); self.listener.close(); self.thread.join(5)
        if self.thread.is_alive() or self.error: raise RuntimeError(self.error or 'Proxy did not stop')

    def summary(self):
        return dict(port=self.port, upstream=self.upstream, connections=self.connections,
                    bytes=self.bytes, partialBytes=self.partial_bytes, error=self.error)
