import contextlib
import importlib.machinery
import importlib.util
import io
import os
import pathlib
import tempfile
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / 'aps-length'


def load_module():
    loader = importlib.machinery.SourceFileLoader('aps_length_mod', str(SCRIPT_PATH))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@contextlib.contextmanager
def pushd(path):
    old_cwd = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old_cwd)


class ApsLengthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_module()

    def test_stop_comment_only_matches_real_latex_comments(self):
        self.assertTrue(
            self.mod._has_stop_comment('% !STOP-APS-LENGTH!\n',
                                       '!STOP-APS-LENGTH!'))
        self.assertTrue(
            self.mod._has_stop_comment('text % !STOP-APS-LENGTH!\n',
                                       '!STOP-APS-LENGTH!'))
        self.assertFalse(
            self.mod._has_stop_comment(r'text \% !STOP-APS-LENGTH!' + '\n',
                                       '!STOP-APS-LENGTH!'))
        self.assertFalse(
            self.mod._has_stop_comment('% !STOP-APS-LENGTH!\n', ''))

    def test_parser_accepts_empty_stop_comment(self):
        parser = self.mod.build_parser()
        opts, _ = parser.parse_args([])
        self.assertEqual(opts.stop_comment, '!STOP-APS-LENGTH!')

        opts, _ = parser.parse_args(['--stop-comment', ''])
        self.assertEqual(opts.stop_comment, '')

    def test_invalid_journal_is_a_parser_error(self):
        parser = self.mod.build_parser()
        opts, _ = parser.parse_args(['--journal', 'NOPE'])

        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                self.mod.validate_options(parser, opts)

    def test_missing_abstract_has_clear_error(self):
        with self.assertRaisesRegex(ValueError, r'\\begin\{abstract\}'):
            self.mod.count_chars_abstract([r'\documentclass{revtex4-2}' + '\n'])

    def test_multiline_includegraphics_with_spaces(self):
        opts = type('Opts', (), {
            'var': None,
            'figs': 'identify',
            'scale_figs': 1.0,
        })()

        old_parse = self.mod._parse_identify_dimensions
        try:
            calls = []
            self.mod._parse_identify_dimensions = (
                lambda filename: (calls.append(filename), (640.0, 480.0))[1])

            with tempfile.TemporaryDirectory() as tmpdir:
                with pushd(tmpdir):
                    pathlib.Path('fig with space.png').touch()
                    with contextlib.redirect_stdout(io.StringIO()):
                        words = self.mod.count_figures_words([
                            r'\begin{figure}' + '\n',
                            r'\includegraphics[width=0.5\textwidth]{fig with' + '\n',
                            ' space}\n',
                            r'\end{figure}' + '\n',
                        ], opts)

            self.assertEqual(words, 132)
            self.assertEqual(calls, ['fig with space.png'])
        finally:
            self.mod._parse_identify_dimensions = old_parse

    def test_wordcount_temp_files_are_cleaned_after_latex_failure(self):
        opts = type('Opts', (), {
            'latex': 'pdflatex',
            'latexopts': '-halt-on-error',
            'ignoreerrors': False,
            'keep_tmp_files': False,
        })()

        old_run = self.mod.subprocess.run
        try:
            def fail_run(*args, **kwargs):
                return type('Completed', (), {
                    'returncode': 1,
                    'stdout': b'latex stdout',
                    'stderr': b'latex stderr',
                })()

            self.mod.subprocess.run = fail_run
            with tempfile.TemporaryDirectory() as tmpdir:
                with pushd(tmpdir):
                    with contextlib.redirect_stdout(io.StringIO()):
                        with self.assertRaisesRegex(RuntimeError, 'LaTeX error'):
                            self.mod.count_main_text_words_wordcount([
                                r'\documentclass{revtex4-2}' + '\n',
                                r'\begin{document}' + '\n',
                                'Body text.\n',
                                r'\end{document}' + '\n',
                            ], opts)
                    self.assertEqual(list(pathlib.Path('.').glob('aps_length_*')),
                                     [])
        finally:
            self.mod.subprocess.run = old_run


if __name__ == '__main__':
    unittest.main()
