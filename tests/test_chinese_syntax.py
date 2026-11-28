from types import SimpleNamespace as Obj
import unittest
from sociolab.chinese_syntax import _coordinates


def document(words):
    tokens = [Obj(start_char=start, end_char=end, text=text,
                  words=[Obj(id=i, text=text, head=head, deprel=rel, upos=pos)])
              for i, start, end, text, head, rel, pos in words]
    return Obj(sentences=[Obj(tokens=tokens)])


class SyntaxBoundaryTests(unittest.TestCase):
    def test_exact_offsets_and_sentence_local_heads(self):
        text = "我 反对。"
        d = document([(1, 0, 1, "我", 2, "nsubj", "PRON"),
                      (2, 2, 4, "反对", 0, "root", "VERB"),
                      (3, 4, 5, "。", 2, "punct", "PUNCT")])
        self.assertEqual(_coordinates(text, d), [[
            {"id": 1, "start": 0, "end": 1, "head": 2, "deprel": "nsubj", "upos": "PRON"},
            {"id": 2, "start": 2, "end": 4, "head": 0, "deprel": "root", "upos": "VERB"},
            {"id": 3, "start": 4, "end": 5, "head": 2, "deprel": "punct", "upos": "PUNCT"}]])

    def test_reject_changed_text_and_omitted_text(self):
        with self.assertRaisesRegex(ValueError, "exact original"):
            _coordinates("我反对", document([(1, 0, 1, "他", 0, "root", "PRON")]))
        with self.assertRaisesRegex(ValueError, "omitted"):
            _coordinates("我反对", document([(1, 0, 1, "我", 0, "root", "PRON")]))

    def test_reject_cycles_and_invalid_head(self):
        for head in (2, 4):
            with self.subTest(head=head), self.assertRaisesRegex(ValueError, "invalid dependency tree"):
                _coordinates("我反对。", document([
                    (1, 0, 1, "我", head, "nsubj", "PRON"),
                    (2, 1, 3, "反对", 1, "dep", "VERB"),
                    (3, 3, 4, "。", 0, "root", "PUNCT")]))

    def test_reject_multiple_roots(self):
        with self.assertRaisesRegex(ValueError, "one dependency root"):
            _coordinates("我反对", document([
                (1, 0, 1, "我", 0, "root", "PRON"),
                (2, 1, 3, "反对", 0, "root", "VERB")]))
