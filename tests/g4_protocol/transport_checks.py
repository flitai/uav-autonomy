"""Real local sockets verify EOF rejection and bounded receive backpressure."""
import importlib.util
import json
from pathlib import Path
import socket
import sys
import threading
import time


def verify(root, directory):
    sys.path.insert(0, str(root / 'src'))
    from sim_bridge.codec import SentinelReader, Decoder, load_schema
    from sim_bridge.transport import TcpCapture
    schema = load_schema(root); decoder = Decoder(schema)
    reader = SentinelReader()
    source = root / 'out/runs/g3-t07-test-20260919-173116-474/headless/amase.bin'
    with source.open('rb') as stream:
        packet = None
        while packet is None and (chunk := stream.read(65536)):
            for frame in reader.feed(chunk):
                if decoder.decode(frame).descriptor == 'afrl.cmasi.AirVehicleState':
                    packet = frame['wire']; break
    assert packet
    directory.mkdir(parents=True, exist_ok=False)
    results = []
    for label in ('fragmented', 'partial-eof', 'invalid-checksum', 'slow-consumer'):
        listener = socket.socket(); listener.bind(('127.0.0.1', 0)); listener.listen()
        client = socket.create_connection(listener.getsockname(), timeout=5)
        server, _ = listener.accept(); server.settimeout(5)
        release, entered = threading.Event(), threading.Event()
        def callback(message, row):
            if label == 'slow-consumer' and not entered.is_set():
                entered.set(); assert release.wait(10), 'Test consumer was not released'
        capture = TcpCapture('127.0.0.1', 0, 'amase', directory / label, schema, {'400', '500'}, callback, sock=client)
        def send():
            try:
                if label == 'slow-consumer':
                    server.sendall(packet)
                    assert entered.wait(5)
                    server.sendall(packet * 20000)
                elif label == 'fragmented':
                    for chunk in (packet[:7], packet[7:31], packet[31:] + packet):
                        server.sendall(chunk)
                elif label == 'partial-eof':
                    server.sendall(packet[:-10])
                else:
                    bad = bytearray(packet); bad[-10] ^= 1; server.sendall(bad)
            except (OSError, AssertionError):
                pass  # Intentional receiver refusal may terminate the sender.
            finally:
                server.close(); listener.close()
        thread = threading.Thread(target=send); thread.start()
        deadline = time.monotonic() + 8
        try:
            while time.monotonic() < deadline:
                if label == 'slow-consumer' and capture.error:
                    break
                if label != 'slow-consumer' and not capture.consumer.is_alive():
                    break
                time.sleep(.02)
            if label == 'slow-consumer':
                assert capture.error and capture.queue_peak == 64, capture.summary()
            elif label == 'fragmented':
                assert capture.error is None and capture.frames == 2 and not capture.reader.buffer
            else:
                assert capture.error and capture.frames == 0, capture.summary()
        finally:
            release.set()
            capture.close(); thread.join(5)
        assert not thread.is_alive()
        results.append({'case': label, 'status': 'passed', 'capture': capture.summary()})
    report = {'status': 'passed', 'cases': results}
    (directory / 'checks.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report


if __name__ == '__main__':
    root = Path(__file__).resolve().parents[2]
    output = root / 'out/runs' / ('g4-t02-sockets-' + time.strftime('%Y%m%d-%H%M%S'))
    print(verify(root, output))
