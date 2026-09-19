"""Test-only main-link relay: truncate one real frame, close both owned sockets."""
import socket
import threading


class DisconnectRelay:
    def __init__(self, protocol, directory, port, amase_port):
        self.protocol, self.directory, self.amase_port = protocol, directory, amase_port
        self.stop, self.armed, self.cut = threading.Event(), threading.Event(), threading.Event()
        self.sockets, self.workers, self.error, self.receipt = [], [], None, None
        self.server = socket.socket()
        try:
            self.server.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            self.server.bind(('127.0.0.1', port))
            self.server.listen(1); self.server.settimeout(0.2)
        except BaseException:
            self.server.close()
            raise
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def disconnect(self):
        self.server.close()
        for sock in list(self.sockets):
            try: sock.shutdown(socket.SHUT_RDWR)
            except OSError: pass
            sock.close()

    def pump(self, source, destination, name):
        reader = self.protocol.wire.sentinel.SentinelReader()
        try:
            with (self.directory / (name + '-received.bin')).open('wb', buffering=0) as received, \
                    (self.directory / (name + '-forwarded.bin')).open('wb', buffering=0) as forwarded:
                while not self.stop.is_set() and not self.cut.is_set():
                    try: data = source.recv(65536)
                    except socket.timeout: continue
                    if not data:
                        raise RuntimeError('Unexpected relay EOF before fault injection')
                    received.write(data)
                    for frame in reader.feed(data):
                        packet = frame['wire']
                        if name == 'amase-to-uxas' and self.armed.is_set() and b'afrl.cmasi.AirVehicleState$' in frame['body']:
                            prefix = packet[:len(packet) // 2]
                            offset = forwarded.tell()
                            destination.sendall(prefix); forwarded.write(prefix)
                            (self.directory / 'cut-frame.bin').write_bytes(packet)
                            (self.directory / 'cut-prefix.bin').write_bytes(prefix)
                            self.receipt = dict(direction=name, sourceFrameOffset=frame['offset'],
                                destinationFrameOffset=offset, fullFrameLength=len(packet), sentBytes=len(prefix),
                                pendingBytes=len(packet) - len(prefix))
                            self.cut.set()
                            self.disconnect()
                            return
                        destination.sendall(packet); forwarded.write(packet)
        except Exception as error:
            if not self.stop.is_set() and not self.cut.is_set(): self.error = repr(error)
        finally:
            (self.directory / (name + '-source-tail.bin')).write_bytes(reader.buffer)

    def run(self):
        try:
            while not self.stop.is_set():
                try: uxas, _ = self.server.accept(); break
                except socket.timeout: continue
            else: return
            self.sockets.append(uxas)
            amase = self.protocol.connect(self.amase_port)
            self.sockets.append(amase)
            for sock in self.sockets:
                sock.settimeout(0.2); sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            for source, destination, name in [(amase, uxas, 'amase-to-uxas'), (uxas, amase, 'uxas-to-amase')]:
                thread = threading.Thread(target=self.pump, args=(source, destination, name), daemon=True)
                self.workers.append(thread); thread.start()
            for thread in self.workers: thread.join()
        except Exception as error:
            if not self.stop.is_set() and not self.cut.is_set(): self.error = repr(error)

    def close(self):
        self.stop.set(); self.disconnect(); self.thread.join(5)
        self.protocol.require(not self.thread.is_alive() and not any(t.is_alive() for t in self.workers),
                              'Relay threads were not reaped')
