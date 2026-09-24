"""Qualified three-task real backend session served from the G5 stage package."""
import argparse
import importlib.util
from pathlib import Path
import sys
import traceback

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('g5_stage_coverage_runtime', ROOT/'scripts/g5_coverage/runtime.py')
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)
c = r.c

class StageSession(r.CoverageSession):
    def prepare(self):
        super().prepare()
        self.record.update(task='G5-T11', scope='packaged-real-terrain-session', stageQualified=False)

    def service(self):
        output = self.run/'map-service'
        package = Path(self.context['stagePackage'])
        return r.state.services.running([self.node, package/'scripts/g5_coverage/server.mjs',
                 Path(self.context['stateCandidate'])/'service.json', output,
                 self.run/'coverage/live.json'], output)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    args.root = ROOT;args.verify = False;args.keep_gui = False;args.mode = 'Gui'
    task = StageSession(args)
    try:task.execute();return 0
    except Exception as error:
        task.record.update(status='failed', error=str(error), traceback=traceback.format_exc())
        print(task.record['traceback'], flush=True);return 1
    finally:c.save(task.run/'runtime-result.json', task.record)

if __name__ == '__main__':sys.exit(main())
