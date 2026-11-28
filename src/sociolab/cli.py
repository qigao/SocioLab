"""Explicit command-line entry points for upstream reference experiments."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from .dataset import load_network
from .diffusion import threshold_report
from .structure import structural_report
from .communities import karate_community_report
from .panels import load_panel, longitudinal_structure_report
from .s50 import s50_reference_report
from .references import karate_club_report
from .keyplayers import karate_keyplayers_report
from .affiliations import davis_affiliation_report
from ._json import unique_object


def _comparison_options(parser: argparse.ArgumentParser, *, groups: bool = False) -> None:
    parser.add_argument("before", help="earlier snapshot JSON")
    parser.add_argument("after", help="later snapshot JSON")
    parser.add_argument("--algorithm", choices=("louvain", "greedy"), default="louvain")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--resolution", type=float, default=1.0)
    if groups:
        parser.add_argument("--group-size", type=int)
        parser.add_argument("--group-members", nargs="+")
        parser.add_argument("--projection", choices=("none", "count", "newman"), default="none")
        parser.add_argument("--max-nodes", type=int, default=200)
        parser.add_argument("--max-edges", type=int, default=2000)
        parser.add_argument("--max-pairs", type=int, default=100000)


def _forecast_report(args: argparse.Namespace) -> dict:
    if args.action in {"s50-history", "s50-target"}:
        from .s50_forecast import load_s50_forecast_history, load_s50_forecast_target

        if args.action == "s50-history":
            history, _ = load_s50_forecast_history(args.archive)
            return history.to_dict()
        return load_s50_forecast_target(args.archive)

    from .behavior_forecast import make_behavior_forecast, score_behavior_forecast

    def read_json(path):
        with Path(path).open(encoding="utf-8") as stream:
            return json.load(stream, object_pairs_hook=unique_object)

    if args.action in {"journal-plan", "journal-evaluate"}:
        from .events import load_event_dataset
        from .journal_evaluation import make_journal_forecast_plan, evaluate_journal_forecasts

        dataset = load_event_dataset(args.dataset)
        if args.action == "journal-plan":
            return make_journal_forecast_plan(
                dataset, read_json(args.specification), read_json(args.schedule),
            )
        from .behavior_forecast import load_behavior_forecast, load_behavior_target

        manifest_path = Path(args.manifest)
        manifest = read_json(manifest_path)
        if (type(manifest) is not dict or set(manifest) != {"schema", "folds"}
                or manifest["schema"] != "sociolab.journal-forecast-fold-manifest.v1"
                or type(manifest["folds"]) is not list):
            raise ValueError("journal evaluation manifest requires a schema and ordered saved folds")
        folds = []
        for entry in manifest["folds"]:
            if type(entry) is not dict or set(entry) != {"forecast", "target"}:
                raise ValueError("each journal evaluation fold requires forecast and target paths")
            if any(type(value) is not str or not value or value.strip() != value for value in entry.values()):
                raise ValueError("journal evaluation paths must be nonempty, trimmed text")
            folds.append({
                "forecast": load_behavior_forecast(manifest_path.parent / entry["forecast"]),
                "target": load_behavior_target(manifest_path.parent / entry["target"]),
            })
        return evaluate_journal_forecasts(read_json(args.plan), dataset, folds)

    if args.action in {"journal-history", "journal-target"}:
        from .events import load_event_dataset
        from .journal_forecast import make_journal_forecast_history, make_journal_forecast_target

        dataset = load_event_dataset(args.dataset)
        specification = read_json(args.specification)
        if args.action == "journal-history":
            bundle = make_journal_forecast_history(dataset, specification)
            return bundle["history"] if args.panel_only else bundle
        bundle = make_journal_forecast_target(
            dataset, specification, read_json(args.prediction), args.knowledge_cutoff,
        )
        return bundle["target"] if args.target_only else bundle

    if args.action == "plan":
        from .forecast_evaluation import make_behavior_forecast_plan

        return make_behavior_forecast_plan(
            load_panel(args.history), read_json(args.specification), args.targets,
        )
    if args.action == "evaluate":
        from .behavior_forecast import load_behavior_forecast, load_behavior_target
        from .forecast_evaluation import evaluate_behavior_forecasts, load_behavior_forecast_plan

        plan = load_behavior_forecast_plan(args.plan)
        manifest_path = Path(args.manifest)
        manifest = read_json(manifest_path)
        if (type(manifest) is not dict or set(manifest) != {"schema", "folds"}
                or manifest["schema"] != "sociolab.behavior-forecast-fold-manifest.v1"
                or type(manifest["folds"]) is not list
                or len(manifest["folds"]) != len(plan["target_time_indices"])):
            raise ValueError("evaluation manifest must list exactly the planned folds")
        folds = []
        for entry in manifest["folds"]:
            if type(entry) is not dict or set(entry) != {"history", "forecast", "target"}:
                raise ValueError("each evaluation fold requires history, forecast and target paths")
            paths = {}
            for name, value in entry.items():
                if type(value) is not str or not value or value.strip() != value:
                    raise ValueError("evaluation input paths must be nonempty, trimmed text")
                paths[name] = manifest_path.parent / value
            folds.append({
                "history": load_panel(paths["history"]),
                "forecast": load_behavior_forecast(paths["forecast"]),
                "target": load_behavior_target(paths["target"]),
            })
        return evaluate_behavior_forecasts(plan, folds)

    if args.action == "create":
        return make_behavior_forecast(load_panel(args.history), read_json(args.specification))
    return score_behavior_forecast(read_json(args.prediction), read_json(args.target))


def _dynamic_report(args: argparse.Namespace) -> dict:
    from .events import EventDataset, ingest_records, load_event_dataset
    from .snapshots import load_snapshot, load_view, materialize_snapshot
    from .communities import community_report
    from .keyplayers import select_key_group, score_key_group
    from .affiliations import affiliation_report
    from .changes import compare_snapshots

    if args.command == "annotations":
        from .annotations import annotation_report
        from .annotation_evaluation import evaluate_annotations

        def method_file(path):
            with Path(path).open(encoding="utf-8") as stream:
                return json.load(stream, object_pairs_hook=unique_object)

        dataset = load_event_dataset(args.dataset)
        if args.action == "inspect":
            return annotation_report(dataset, knowledge_cutoff=args.knowledge_cutoff,
                                     method=None if args.method is None else method_file(args.method))
        return evaluate_annotations(dataset, reference_method=method_file(args.reference_method),
                                    candidate_method=method_file(args.candidate_method),
                                    knowledge_cutoff=args.knowledge_cutoff)

    if args.command == "events":
        if args.action == "init":
            if args.clock == "ticks" and not args.run_id:
                raise ValueError("a ticks clock requires --run-id")
            if args.clock == "utc" and args.run_id:
                raise ValueError("UTC clocks do not use --run-id")
            clock = {"kind": "utc"} if args.clock == "utc" else {"kind": "ticks", "run_id": args.run_id}
            return EventDataset.from_mapping({"schema": "sociolab.events.v1", "dataset_id": args.dataset_id,
                "origin": args.origin, "source_revision": args.source_revision, "clock": clock, "records": []}).to_dict()
        dataset = load_event_dataset(args.dataset)
        if args.action == "import":
            with Path(args.batch).open(encoding="utf-8") as stream:
                batch = json.load(stream, object_pairs_hook=unique_object)
            return ingest_records(dataset, batch, received_at=args.received_at).to_dict()
        return {"kind": "EVENT_DATASET_VALIDATION", "schema": "sociolab.events.v1",
                "dataset_id": dataset.dataset_id, "origin": dataset.origin, "valid": True,
                "record_count": len(dataset.records), "effective_assertion_count": len(dataset.as_known()),
                "content_hash": dataset.content_hash}
    if args.command == "snapshot":
        dataset = load_event_dataset(args.dataset)
        return materialize_snapshot(dataset, load_view(args.view, dataset.clock), args.knowledge_cutoff).to_dict()
    if args.command == "changes" or (args.command == "communities" and args.analysis == "compare"):
        options = {"algorithm": args.algorithm, "seed": args.seed, "resolution": args.resolution}
        if args.command == "changes":
            options.update(group_size=args.group_size, group_members=args.group_members, projection=args.projection,
                           max_nodes=args.max_nodes, max_edges=args.max_edges, max_pairs=args.max_pairs)
        result = compare_snapshots(load_snapshot(args.before), load_snapshot(args.after), **options)
        if args.command == "communities":
            return {"kind": "DESCRIPTIVE_COMMUNITY_CHANGE", "inputs": result["inputs"],
                    "population": result["population"], "communities": result["communities"]}
        return result
    snapshot = load_snapshot(args.snapshot)
    snapshot.require_complete()
    if snapshot.bipartite != (args.command == "affiliations"):
        raise ValueError("person–activity snapshots require affiliation analysis; person-only snapshots require network analysis")
    graph = snapshot.to_graph()
    if args.command == "communities":
        result = community_report(graph, algorithm=args.algorithm, seed=args.seed, resolution=args.resolution)
    elif args.command == "affiliations":
        result = affiliation_report(graph, snapshot.persons, projection=args.projection, max_pairs=args.max_pairs)
    elif args.analysis == "select":
        result = select_key_group(graph, args.group_size, max_nodes=args.max_nodes, max_edges=args.max_edges)
    else:
        result = score_key_group(graph, args.members)
    result["input"] = {"snapshot_hash": snapshot.content_hash, "dataset": snapshot.to_dict()["dataset"],
                       "view": snapshot.view, "knowledge_cutoff": snapshot.to_dict()["knowledge_cutoff"]}
    if snapshot.view["mode"] == "annotations":
        result["input"]["annotation_summary"] = snapshot.to_dict()["annotation_summary"]
        result["measurement_basis"] = "derived_from_annotations"
        result["automatic_annotation_qualified"] = False
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sociolab")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("davis", help="analyze Davis 1941 person-event affiliation reference")
    communities = commands.add_parser("communities", help="community analysis; no subcommand runs the Karate reference")
    community_actions = communities.add_subparsers(dest="analysis")
    community_analyze = community_actions.add_parser("analyze", help="analyze a typed person-network snapshot")
    community_analyze.add_argument("snapshot")
    community_analyze.add_argument("--algorithm", choices=("louvain", "greedy"), default="louvain")
    community_analyze.add_argument("--seed", type=int, default=0)
    community_analyze.add_argument("--resolution", type=float, default=1.0)
    _comparison_options(community_actions.add_parser("compare", help="compare communities under an identical view policy"))
    commands.add_parser("karate", help="analyze published Zachary network using upstream NetworkX")
    keyplayers = commands.add_parser("keyplayers", help="upstream NetworkX prominent-group search on the published Karate graph")
    keyplayers.add_argument("--size", type=int, default=2)
    key_actions = keyplayers.add_subparsers(dest="analysis")
    key_select = key_actions.add_parser("select", help="select a group on a connected undirected unit-strength snapshot")
    key_select.add_argument("snapshot")
    key_select.add_argument("--size", type=int, default=2, dest="group_size")
    key_select.add_argument("--max-nodes", type=int, default=200)
    key_select.add_argument("--max-edges", type=int, default=2000)
    key_score = key_actions.add_parser("score", help="score a supplied group using original NetworkX")
    key_score.add_argument("snapshot")
    key_score.add_argument("--members", nargs="+", required=True)
    events = commands.add_parser("events", help="strict, versioned observation input and receipt assignment")
    event_actions = events.add_subparsers(dest="action", required=True)
    event_init = event_actions.add_parser("init", help="create an empty event dataset JSON")
    event_init.add_argument("--dataset-id", required=True)
    event_init.add_argument("--origin", choices=("synthetic", "external_observation", "simulation_export"), required=True)
    event_init.add_argument("--source-revision", required=True)
    event_init.add_argument("--clock", choices=("utc", "ticks"), required=True)
    event_init.add_argument("--run-id")
    event_validate = event_actions.add_parser("validate", help="validate all receipt prefixes, references and revisions")
    event_validate.add_argument("dataset")
    event_import = event_actions.add_parser("import", help="append raw source records with importer-owned receipts; writes JSON to stdout")
    event_import.add_argument("dataset")
    event_import.add_argument("batch", help="JSON array of records without ingest_seq/recorded_at")
    event_import.add_argument("--received-at", help="explicit nondecreasing UTC receipt time for reproducible imports")
    tracking = commands.add_parser("tracking", help="local receipt-driven tracking of fixed source-time views")
    tracking_actions = tracking.add_subparsers(dest="action", required=True)
    tracking_init = tracking_actions.add_parser("init", help="create a new private append-only tracking store")
    tracking_init.add_argument("dataset", help="validated initial journal JSON")
    tracking_init.add_argument("registration", help="fixed network tracking registration JSON")
    tracking_init.add_argument("store", help="new local directory; existing directories are not overwritten")
    tracking_run = tracking_actions.add_parser("run", help="consume strict JSONL batches from stdin until EOF")
    tracking_run.add_argument("store")
    tracking_inspect = tracking_actions.add_parser("inspect", help="replay retained checkpoints and summarize the current version")
    tracking_inspect.add_argument("store")
    annotations = commands.add_parser("annotations", help="inspect versioned labels or compare them with a human reference")
    annotation_actions = annotations.add_subparsers(dest="action", required=True)
    annotation_inspect = annotation_actions.add_parser("inspect", help="report current, stale and ambiguous annotations without loading source content")
    annotation_inspect.add_argument("dataset")
    annotation_inspect.add_argument("--method", help="exact method JSON: kind, id, version; omitted means all methods")
    annotation_inspect.add_argument("--knowledge-cutoff", type=int)
    annotation_evaluate = annotation_actions.add_parser("evaluate", help="report agreement and missing labels; does not qualify a model")
    annotation_evaluate.add_argument("dataset")
    annotation_evaluate.add_argument("--reference-method", required=True, help="human reference method JSON")
    annotation_evaluate.add_argument("--candidate-method", required=True, help="distinct candidate method JSON")
    annotation_evaluate.add_argument("--knowledge-cutoff", type=int)
    snapshot = commands.add_parser("snapshot", help="materialize a typed temporal view with evidence and unknowns")
    snapshot.add_argument("dataset")
    snapshot.add_argument("view")
    snapshot.add_argument("--knowledge-cutoff", type=int)
    affiliations = commands.add_parser("affiliations", help="analyze a person–activity snapshot")
    affiliation_actions = affiliations.add_subparsers(dest="analysis", required=True)
    affiliation_analyze = affiliation_actions.add_parser("analyze")
    affiliation_analyze.add_argument("snapshot")
    affiliation_analyze.add_argument("--projection", choices=("none", "count", "newman"), default="none")
    affiliation_analyze.add_argument("--max-pairs", type=int, default=100000)
    _comparison_options(commands.add_parser("changes", help="evidence-backed descriptive network changes"), groups=True)
    panel = commands.add_parser("panel", help="descriptive multi-wave NetworkX metrics; no influence or causal estimation")
    panel.add_argument("dataset")
    s50 = commands.add_parser("s50", help="read official s50-format ZIP as a numerical example; not causal evidence")
    s50.add_argument("archive", help="locally supplied s50_data.zip from the original research site")
    source = commands.add_parser("source", help="audit source observations and unresolved admission requirements")
    source_formats = source.add_subparsers(dest="source_format", required=True)
    mauldin = source_formats.add_parser("mauldin", help="audit the locally supplied Mauldin MSW data archive")
    mauldin_actions = mauldin.add_subparsers(dest="action", required=True)
    mauldin_inspect = mauldin_actions.add_parser("inspect", help="report aggregate provenance, coverage and nomination records")
    mauldin_inspect.add_argument("archive", help="local UTA_Social_Networks_Social_Good.zip; no automatic download")
    study = commands.add_parser("study", help="reproduce a bounded descriptive source case")
    study_sources = study.add_subparsers(dest="study_source", required=True)
    contact_study = study_sources.add_parser("hypertext2009", help="compare recorded proximity graphs from the reviewed official TSV gzip")
    contact_study.add_argument("archive", help="local ht2009_contact_list.dat.gz; no automatic download")
    forecast = commands.add_parser("forecast", help="create past-only behavior point predictions, then score separate future observations")
    forecast_actions = forecast.add_subparsers(dest="action", required=True)
    forecast_create = forecast_actions.add_parser("create", help="use a historical panel only; output contains private per-actor predictions")
    forecast_create.add_argument("history", help="historical sociolab.longitudinal.v1 panel; no target wave")
    forecast_create.add_argument("specification", help="sociolab.behavior-forecast.v1 specification")
    forecast_score = forecast_actions.add_parser("score", help="score a saved prediction without fitting; output is aggregate")
    forecast_score.add_argument("prediction", help="saved forecast JSON from create")
    forecast_score.add_argument("target", help="separate sociolab.behavior-target.v1 observations; no future network")
    journal_history = forecast_actions.add_parser("journal-history", help="rebuild private history and evidence at one explicit receipt cutoff")
    journal_history.add_argument("dataset", help="sociolab.events.v1 receipt-versioned journal")
    journal_history.add_argument("specification", help="sociolab.journal-forecast-history.v1 selection and frozen cutoff")
    journal_history.add_argument("--panel-only", action="store_true", help="emit only the panel for forecast create; preserve the full bundle separately")
    journal_target = forecast_actions.add_parser("journal-target", help="extract private target behavior bound to a saved forecast; no future network or refit")
    journal_target.add_argument("dataset", help="same journal, optionally with later receipts")
    journal_target.add_argument("specification", help="unchanged journal history specification used at issuance")
    journal_target.add_argument("prediction", help="saved behavior forecast from that history")
    journal_target.add_argument("--knowledge-cutoff", type=int, required=True, help="explicit target receipt cutoff; at least the history cutoff")
    journal_target.add_argument("--target-only", action="store_true", help="emit only the target for forecast score; preserve the full bundle separately")
    journal_plan = forecast_actions.add_parser("journal-plan", help="freeze private multi-origin receipt and target cutoffs from the initial journal only")
    journal_plan.add_argument("dataset", help="journal ending exactly at the initial history cutoff")
    journal_plan.add_argument("specification", help="initial sociolab.journal-forecast-history.v1 specification")
    journal_plan.add_argument("schedule", help="sociolab.journal-forecast-schedule.v1 with both cutoffs for every fold")
    journal_evaluate = forecast_actions.add_parser("journal-evaluate", help="evaluate all saved forecasts at planned journal versions without refitting")
    journal_evaluate.add_argument("plan", help="saved private sociolab.journal-forecast-plan.v1")
    journal_evaluate.add_argument("dataset", help="same journal with enough appended receipts for every planned cutoff")
    journal_evaluate.add_argument("manifest", help="ordered saved forecast/target paths relative to this manifest")
    forecast_plan = forecast_actions.add_parser("plan", help="fix a multi-origin schedule using only the initial history and specification")
    forecast_plan.add_argument("history", help="initial historical panel; no planned target observations")
    forecast_plan.add_argument("specification", help="first-origin forecast specification; models and scale stay fixed")
    forecast_plan.add_argument("--targets", nargs="+", type=int, required=True, help="consecutive future wave indices in evaluation order")
    forecast_evaluate = forecast_actions.add_parser("evaluate", help="score saved forecasts across every planned origin without refitting")
    forecast_evaluate.add_argument("plan", help="saved sociolab.behavior-forecast-plan.v1 JSON")
    forecast_evaluate.add_argument("manifest", help="ordered history/forecast/target file paths, relative to this manifest")
    for action, help_text in (
        ("s50-history", "extract waves 0/1 only for a numerical teaching example; private actor data"),
        ("s50-target", "extract wave 2 behavior only after predictions are saved; private actor data"),
    ):
        source_action = forecast_actions.add_parser(action, help=help_text)
        source_action.add_argument("archive", help="local s50_data.zip; no automatic download")
    partial = commands.add_parser("partial", help="explicit present/absent/unknown fixed-cohort network observations")
    partial_actions = partial.add_subparsers(dest="action", required=True)
    for action, help_text in (("inspect", "describe endpoint changes and observation coverage"),
                              ("model", "inspect original upstream masks and targets without fitting"),
                              ("fit", "fit the conditional network-only cusna CPU profile")):
        partial_action = partial_actions.add_parser(action, help=help_text)
        partial_action.add_argument("dataset", help="sociolab.partial-network.v1 JSON")
        if action == "fit":
            partial_action.add_argument("--seed", type=int, default=1234)
            partial_action.add_argument("--n1", type=int, default=1000)
            partial_action.add_argument("--nd", type=int, default=1000)
            partial_action.add_argument("--n3", type=int, default=4000)
            partial_action.add_argument("--batch2", type=int, default=256)
            partial_action.add_argument("--n2", type=int, nargs=4, default=(40, 40, 60, 80))
    saom = commands.add_parser("saom", help="fit the upstream CPU model and report numerical convergence")
    saom.add_argument("dataset", help="longitudinal panel JSON or s50 archive")
    saom.add_argument("--format", choices=("panel", "s50"), default="panel")
    saom.add_argument("--seed", type=int, default=1234)
    saom.add_argument("--n1", type=int, default=1000)
    saom.add_argument("--nd", type=int, default=1000, help="simulations for each derivative batch")
    saom.add_argument("--n3", type=int, default=4000)
    saom.add_argument("--batch2", type=int, default=256)
    saom.add_argument("--n2", type=int, nargs=4, default=(40, 40, 60, 80),
                      help="iteration counts for the four phase-2 subphases")
    coevolution = commands.add_parser("coevolution", help="inspect or fit a declared network/ordinal-behavior model")
    coevolution_actions = coevolution.add_subparsers(dest="action", required=True)
    for action in ("inspect", "fit"):
        joint = coevolution_actions.add_parser(action)
        joint.add_argument("dataset", help="longitudinal panel JSON or original-format s50 archive")
        joint.add_argument("specification", help="explicit coevolution profile and declared ordinal scale JSON")
        joint.add_argument("--format", choices=("panel", "s50"), default="panel")
        if action == "fit":
            joint.add_argument("--seed", type=int, default=1234)
            joint.add_argument("--n1", type=int, default=1000)
            joint.add_argument("--nd", type=int, default=1000)
            joint.add_argument("--n3", type=int, default=4000)
            joint.add_argument("--batch2", type=int, default=256)
            joint.add_argument("--n2", type=int, nargs=4, default=(40, 40, 60, 80))
    structure = commands.add_parser("structure", help="run upstream NetworkX structure metrics")
    structure.add_argument("dataset")
    threshold = commands.add_parser("threshold", help="run upstream NDlib ThresholdModel")
    threshold.add_argument("dataset")
    threshold.add_argument("--seeds", nargs="+", required=True)
    threshold.add_argument("--threshold", type=float, required=True)
    threshold.add_argument("--steps", type=int, required=True)
    threshold.add_argument("--random-seed", type=int, default=0)
    args = parser.parse_args(argv)
    if args.command == "tracking":
        from .events import load_event_dataset
        from .tracking_store import initialize_tracking_store, consume_tracking_stream, inspect_tracking_store

        try:
            if args.action == "init":
                with Path(args.registration).open(encoding="utf-8") as stream:
                    registration = json.load(stream, object_pairs_hook=unique_object)
                report = initialize_tracking_store(args.store, load_event_dataset(args.dataset), registration)
            elif args.action == "inspect":
                report = inspect_tracking_store(args.store)
            else:
                consume_tracking_stream(args.store, sys.stdin, sys.stdout)
                return 0
        except (ValueError, OSError) as error:
            parser.error(str(error))
    elif args.command in {"events", "snapshot", "affiliations", "changes", "annotations"} or (
        args.command in {"communities", "keyplayers"} and args.analysis is not None
    ):
        try:
            report = _dynamic_report(args)
        except (ValueError, OSError) as error:
            parser.error(str(error))
    elif args.command == "source":
        from .mauldin import mauldin_source_report

        try:
            report = mauldin_source_report(args.archive)
        except (ValueError, OSError) as error:
            parser.error(str(error))
    elif args.command == "study":
        from .recorded_contacts import hypertext2009_case_report

        try:
            report = hypertext2009_case_report(args.archive)
        except (ValueError, OSError) as error:
            parser.error(str(error))
    elif args.command == "forecast":
        try:
            report = _forecast_report(args)
        except (ValueError, OSError) as error:
            parser.error(str(error))
    elif args.command == "partial":
        from .partial_panels import load_partial_panel
        from .partial_changes import partial_panel_report

        try:
            partial_panel = load_partial_panel(args.dataset)
            if args.action == "inspect":
                report = partial_panel_report(partial_panel)
            else:
                from .partial_saom import partial_network_model_report, fit_partial_network_saom
                if args.action == "model":
                    report = partial_network_model_report(partial_panel)
                else:
                    report = fit_partial_network_saom(
                        partial_panel, seed=args.seed, n1=args.n1, nD=args.nd,
                        n3=args.n3, batch2=args.batch2, n2=tuple(args.n2),
                    )
        except (ValueError, OSError) as error:
            parser.error(str(error))
    elif args.command == "coevolution":
        from .coevolution import coevolution_model_report, fit_coevolution_saom
        from .coevolution_input import load_coevolution_spec
        from .s50 import load_s50_archive

        try:
            spec = load_coevolution_spec(args.specification)
            if args.format == "s50":
                panel, provenance = load_s50_archive(args.dataset)
            else:
                panel, provenance = load_panel(args.dataset), None
            if args.action == "inspect":
                report = coevolution_model_report(panel, spec)
            else:
                report = fit_coevolution_saom(
                    panel, spec, seed=args.seed, n1=args.n1, nD=args.nd,
                    n3=args.n3, batch2=args.batch2, n2=tuple(args.n2),
                )
            if provenance is not None:
                report.update(provenance)
                report.update(
                    sample_has_valid_population_boundary=False,
                    suitable_for_empirical_influence_estimation=False,
                    usage_limit="numerical illustration only: s50 is not a properly delineated network",
                )
        except (ValueError, OSError) as error:
            parser.error(str(error))
    elif args.command == "saom":
        from .saom import fit_network_saom, fit_s50_network_reference

        settings = {
            "seed": args.seed, "n1": args.n1, "nD": args.nd,
            "n3": args.n3, "batch2": args.batch2, "n2": tuple(args.n2),
        }
        if args.format == "s50":
            report = fit_s50_network_reference(args.dataset, **settings)
        else:
            report = fit_network_saom(load_panel(args.dataset), **settings)
    elif args.command == "s50":
        report = s50_reference_report(args.archive)
    elif args.command == "panel":
        report = longitudinal_structure_report(load_panel(args.dataset))
    elif args.command == "communities":
        report = karate_community_report()
    elif args.command == "davis":
        report = davis_affiliation_report()
    elif args.command == "karate":
        report = karate_club_report()
    elif args.command == "keyplayers":
        report = karate_keyplayers_report(group_size=args.size)
    elif args.command == "structure":
        report = structural_report(load_network(args.dataset))
    else:
        dataset = load_network(args.dataset)
        report = threshold_report(
            dataset, seeds=tuple(sorted(args.seeds)), threshold=args.threshold,
            steps=args.steps, random_seed=args.random_seed,
        )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False))
    if (args.command == "saom" or (args.command in {"coevolution", "partial"} and args.action == "fit")) and not report["convergence_is_validated"]:
        return 2
    return 0
