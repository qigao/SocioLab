import unittest

from sociolab.predicate_nli import _probe_specs, native_entailment, screen_global_candidate


def row(role, scores=None, index=0, status="SCORED"):
    return {"frame_index": index, "holder_candidate": {"role": role}, "status": status,
        "scores": scores if scores is not None else {"entailment": .8, "neutral": .1, "contradiction": .1}}


class PredicateNliBoundaryTests(unittest.TestCase):
    def test_original_fragment_retains_local_negation(self):
        text = "我不赞成这个方案。"
        frames = [{"predicate": {"start": 2, "end": 4},
            "modifiers": [{"start": 1, "end": 2, "deprel": "advmod"},
                          {"start": 8, "end": 9, "deprel": "punct"}],
            "holder_candidate": {"role": "SOURCE_SPEAKER_CANDIDATE"}}]
        probe, = _probe_specs(text, frames)
        self.assertEqual(probe["probe_span"], {"start": 1, "end": 4})
        self.assertEqual(probe["premise"], "不赞成")
        self.assertEqual(probe["scope"], "LOCAL_FRAGMENT_NOT_ASSERTION")

    def test_no_holder_resolution_from_local_entailment(self):
        for role in ("EXPLICIT_SUBJECT_HEAD", "QUOTE_GOVERNOR_SUBJECT_CANDIDATE", "UNRESOLVED"):
            with self.subTest(role=role):
                r = screen_global_candidate(row("UNRESOLVED"), [row(role)])
                self.assertEqual(r["status"], "UNRESOLVED")
                self.assertEqual(r["supporting_frame_indices"], [])

    def test_native_ties_and_unsupported_stay_unresolved(self):
        self.assertFalse(native_entailment(row("SOURCE_SPEAKER_CANDIDATE",
            {"entailment": .5, "neutral": .5, "contradiction": 0.})))
        self.assertFalse(native_entailment(row("SOURCE_SPEAKER_CANDIDATE", status="INPUT_TOO_LONG")))
        n = row("SOURCE_SPEAKER_CANDIDATE", {"entailment": .1, "neutral": .8, "contradiction": .1})
        r = screen_global_candidate(row("UNRESOLVED"), [n])
        self.assertEqual(r["status"], "UNRESOLVED")

    def test_both_scores_required_but_no_topic_binding(self):
        local = row("SOURCE_SPEAKER_CANDIDATE", index=2)
        retained = screen_global_candidate(row("UNRESOLVED"), [local])
        self.assertEqual(retained["status"], "RETAINED_UNQUALIFIED_CANDIDATE")
        self.assertEqual(retained["supporting_frame_indices"], [2])
        self.assertEqual(retained["joint_topic_binding"], "NOT_ESTABLISHED")
        global_negative = row("UNRESOLVED", {"entailment": .1, "neutral": .1, "contradiction": .8})
        self.assertEqual(screen_global_candidate(global_negative, [local])["status"], "UNRESOLVED")

    def test_no_frames_is_not_negative(self):
        r = screen_global_candidate(row("UNRESOLVED"), [])
        self.assertEqual(r["status"], "UNRESOLVED")
        self.assertTrue(r["global_native_entailment"])
