"""Run the qualified B07 backend with a B08 combined viewer package."""
import argparse
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
import traceback

ROOT = Path(__file__).resolve().parents[2]
spec = spec_from_file_location('g6_b07_session', ROOT / 'scripts/g6_lifecycle/session.py')
b07 = module_from_spec(spec)
spec.loader.exec_module(b07)
c = b07.c


class StageSession(b07.LifecycleSession):
    def inputs(self):
        paths = [p for p in (ROOT / 'scripts/g6_stage').rglob('*.py')]
        return super().inputs() + c.base.inventory(ROOT, paths)

    def prepare(self):
        super().prepare()
        stage_spec = spec_from_file_location('g6_b08_manage', ROOT / 'scripts/g6_stage/manage.py')
        stage_manage = module_from_spec(stage_spec)
        stage_spec.loader.exec_module(stage_manage)
        candidate = stage_manage.check_candidate(self.args.stage_build)
        self.viewer_service = candidate / 'service.json'
        self.record.update(b08StageBuildRunId=self.args.stage_build,
                           b08StageBuildSHA256=c.sha(candidate.parent / 'manifest.json'))

    def execute(self):
        super().execute()
        self.record.update(task='G6-B08', scope='combined-stage-candidate',
                           stageQualified=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--stage-build', required=True)
    parser.add_argument('--viewer-build', default='g6-a03-build-20260924-2330')
    parser.add_argument('--draft-build', default='g6-b03-build-20260924-2438')
    parser.add_argument('--execution-build', default='g6-b04-build-20260928-duration02')
    parser.add_argument('--assignment-build', default='g6-b05-build-20260930-05')
    parser.add_argument('--replanning-build', default='g6-b06-build-20261004-09')
    parser.add_argument('--lifecycle-build', default='g6-b07-build-20261009-09')
    parser.add_argument('--planner-deadline-seconds', type=int, default=90)
    parser.add_argument('--mode', choices=('Headless', 'Gui'), default='Headless')
    args = parser.parse_args()
    args.root = ROOT
    args.verify = False
    args.keep_gui = False
    c.need(args.run_id.startswith('g6-b08-session-'), 'B08 session ID required')
    run = ROOT / 'out/runs' / args.run_id
    c.need(not run.exists(), 'B08 session ID exists')
    run.mkdir(parents=True)
    b07.b06.assignment_session.execution_session.draft_session.control_session.context_for(
        run, args.viewer_build)
    task = StageSession(args)
    try:
        task.execute()
        return 0
    except Exception as error:
        task.record.update(task='G6-B08', status='failed', error=str(error),
                           traceback=traceback.format_exc())
        print(task.record['traceback'], file=sys.stderr)
        return 1
    finally:
        c.save(run / 'runtime-result.json', task.record)


if __name__ == '__main__':
    sys.exit(main())
