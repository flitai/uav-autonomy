"""Read-only TCP capture with bounded queues and per-connection evidence."""
from collections import Counter, deque
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import queue
import socket
import threading
import time

from .codec import Decoder, SentinelReader, check_source


class TcpCapture:
    def __init__(self, host, port, channel, folder, schema, entity_ids, on_message=None, sock=None):
        self.channel, self.folder, self.entity_ids = channel, Path(folder), set(entity_ids)
        self.folder.mkdir(parents=True, exist_ok=False)
        self.sock = sock or socket.create_connection((host, port), timeout=5)
        self.sock.settimeout(.5)
        self.decoder, self.reader = Decoder(schema), SentinelReader()
        self.on_message = on_message
        self.queue = queue.Queue(maxsize=64)
        self.recent = deque(maxlen=64)
        self.latest, self.counts = {}, Counter()
        self.stop = threading.Event()
        self.disconnected = False
        self.error = None
        self.bytes_received, self.frames, self.queue_peak = 0, 0, 0
        self.last_received = None
        self.lock = threading.Lock()
        self.receiver = threading.Thread(target=self.receive, name='g4-' + channel + '-receive', daemon=True)
        self.consumer = threading.Thread(target=self.consume, name='g4-' + channel + '-decode', daemon=True)
        self.consumer.start(); self.receiver.start()

    def receive(self):
        try:
            while not self.stop.is_set():
                try:
                    chunk = self.sock.recv(65536)
                except socket.timeout:
                    continue
                if not chunk:
                    break
                self.queue.put_nowait((chunk, time.monotonic(), datetime.now(timezone.utc).isoformat()))
                self.queue_peak = max(self.queue_peak, self.queue.qsize())
        except Exception as error:
            if not self.stop.is_set():
                self.error = str(error) or type(error).__name__
        finally:
            self.disconnected = True
            self.sock.close()

    def consume(self):
        try:
            with (self.folder / 'raw.bin').open('wb') as raw_file, (self.folder / 'messages.jsonl').open('w', encoding='utf-8') as records:
                while not self.disconnected or not self.queue.empty():
                    try:
                        chunk, received, wall = self.queue.get(timeout=.2)
                    except queue.Empty:
                        continue
                    raw_file.write(chunk); raw_file.flush()
                    self.bytes_received += len(chunk)
                    for frame in self.reader.feed(chunk):
                        message = self.decoder.decode(frame)
                        check_source(message, self.channel, self.entity_ids)
                        row = message.metadata()
                        row.update(offset=frame['offset'], length=frame['length'], receivedAt=wall, monotonicSeconds=received,
                                   wireSHA256=hashlib.sha256(frame['wire']).hexdigest())
                        records.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n'); records.flush()
                        with self.lock:
                            self.frames += 1
                            self.counts[message.descriptor] += 1
                            key = message.fields.get('ID', message.fields.get('TaskID', ''))
                            # This cache is diagnostic only; never accumulates a whole run.
                            if message.descriptor in ('afrl.cmasi.AirVehicleState', 'afrl.cmasi.AirVehicleConfiguration',
                                                      'afrl.cmasi.SessionStatus'):
                                self.latest[(message.descriptor, key)] = row
                            self.recent.append(row)
                            self.last_received = received
                        if self.on_message:
                            self.on_message(message, row)
                if not self.stop.is_set():
                    self.reader.eof()
        except Exception as error:
            self.error = repr(error)
            self.stop.set()
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.sock.close()
        finally:
            (self.folder / 'tail.bin').write_bytes(self.reader.buffer)
            self.write_summary()

    def summary(self):
        with self.lock:
            return {'channel': self.channel, 'frames': self.frames, 'bytes': self.bytes_received,
                    'types': dict(self.counts), 'queuePeakChunks': self.queue_peak, 'queueLimitChunks': 64,
                    'recentLimit': 64, 'tailBytes': len(self.reader.buffer), 'error': self.error,
                    'disconnected': self.disconnected, 'sentBusinessFrames': 0,
                    'lastReceivedMonotonic': self.last_received}

    def write_summary(self):
        (self.folder / 'summary.json').write_text(json.dumps(self.summary(), indent=2) + '\n', encoding='utf-8')

    def close(self):
        self.stop.set()
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.sock.close()
        self.receiver.join(5); self.consumer.join(5)
        if self.receiver.is_alive() or self.consumer.is_alive():
            raise RuntimeError('TCP capture threads did not stop')
        self.write_summary()
