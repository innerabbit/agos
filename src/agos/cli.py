from __future__ import annotations
import argparse, json
from .storage import SQLiteStateStore

def main() -> None:
    parser=argparse.ArgumentParser(prog="agos",description="Local AGOS vertical-slice utilities")
    sub=parser.add_subparsers(dest="command",required=True)
    events=sub.add_parser("events",help="print durable events for a local run"); events.add_argument("database"); events.add_argument("run_id")
    demo=sub.add_parser("research-to-publish-demo", help="run the local-only fixture research-to-publish demo")
    demo.add_argument("--output-dir", default="./artifacts/research-to-publish")
    demo_mode = demo.add_mutually_exclusive_group()
    demo_mode.add_argument("--reject", action="store_true", help="exercise rejection; no artifact is written")
    demo_mode.add_argument("--dry-run", action="store_true", help="exercise approved workflow without writing an artifact")
    args=parser.parse_args()
    if args.command=="events": print(json.dumps(SQLiteStateStore(args.database).events(args.run_id),indent=2))
    if args.command=="research-to-publish-demo":
        from pathlib import Path
        from .research_to_publish import SourceFixture, build_workflow, register_local_workflow
        from .memory import InMemoryMemoryStore
        from .providers import DeterministicProvider
        from .registry import CapabilityRegistry
        from .runtime import Runtime
        fixtures={"dag-guide": SourceFixture("dag-guide", "DAG guide", "fixture://dag-guide", "2026-10-11T00:00:00Z", "DAGs make dependencies explicit.")}
        brief={"id":"demo-1","title":"A local workflow demo","slug":"local-workflow-demo","provider_prompt":"demo-draft"}
        registry=CapabilityRegistry(); memory=InMemoryMemoryStore()
        register_local_workflow(registry,memory,fixtures,DeterministicProvider({"demo-draft":{"markdown":"Dependencies are explicit [dag-guide].","claims":[{"text":"Dependencies are explicit.","source_id":"dag-guide"}]}}),Path(args.output_dir),dry_run=args.dry_run)
        state=Runtime(registry,SQLiteStateStore(":memory:")).run(build_workflow(brief,["dag-guide"],"rejected" if args.reject else "approved"),"research-to-publish-demo")
        print(json.dumps({"status":state.status,"publish_status":state.nodes["publish"].status,"publish":state.nodes["publish"].output},indent=2))
if __name__=="__main__": main()
