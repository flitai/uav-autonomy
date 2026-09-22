"""Optional display worker. The simulation and qualified gateway remain independent."""
import importlib.util
import json
import sqlite3
from pathlib import Path
import threading
import time
import traceback

spec=importlib.util.spec_from_file_location('coverage_engine',Path(__file__).with_name('engine.py'))
engine=importlib.util.module_from_spec(spec);spec.loader.exec_module(engine)


def atomic(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    data=json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False)
    engine.need(len(data.encode()) <= 8*1024*1024,'Coverage snapshot exceeds budget')
    temporary=path.with_suffix('.tmp')
    temporary.write_text(data,encoding='utf-8')
    for attempt in range(10):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt==9:raise
            time.sleep(.02)


class Collector:
    def __init__(self, manifest_path, terrain_directory, path):
        self.manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
        self.path=path
        self.engine=engine.Coverage(self.manifest['run_id'],engine.Terrain(terrain_directory))
        self.stopping=threading.Event()
        self.error=None
        self.thread=threading.Thread(target=self.work,name='coverage-read-only',daemon=True)

    def start(self):
        atomic(self.path,dict(status='recovering',runId=self.engine.run_id,updatedAtMs=time.time_ns()//1000000))
        self.thread.start()

    def work(self):
        try:
            ready_deadline=time.monotonic()+30
            while not self.stopping.is_set():
                try:
                    caught_up=engine.read_batch(Path(self.manifest['ledger_path']),self.manifest,self.engine)
                except sqlite3.OperationalError as error:
                    # Gateway startup precedes journal creation. Only these
                    # initial states get a bounded retry; corruption/identity
                    # failures and errors after consuming records are fatal.
                    initial=any(reason in str(error) for reason in ('unable to open database file','no such table','Coverage ledger not initialized'))
                    if self.engine.cursor!=(0,0) or not initial or time.monotonic()>=ready_deadline:raise
                    caught_up=False
                if self.engine.cursor==(0,0):
                    engine.need(time.monotonic()<ready_deadline,'Coverage ledger readiness timeout')
                atomic(self.path,dict(self.engine.snapshot(),status='live' if caught_up else 'recovering',updatedAtMs=time.time_ns()//1000000))
                self.stopping.wait(.5 if caught_up else .01)
        except Exception as error:
            self.error=str(error)
            atomic(self.path,dict(status='failed',runId=self.engine.run_id,error=self.error,updatedAtMs=time.time_ns()//1000000))
            self.path.with_name('collector-error.txt').write_text(traceback.format_exc(),encoding='utf-8')

    def stop(self):
        self.stopping.set()
        self.thread.join(10)
        engine.need(not self.thread.is_alive(),'Coverage worker did not exit normally')
        result=dict(status='failed' if self.error else 'passed',error=self.error,normalExit=True,
                    runId=self.engine.run_id,cursor=self.engine.cursor,sampledStates=self.engine.states)
        return result
