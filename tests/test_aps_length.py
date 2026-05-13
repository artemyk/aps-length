import builtins
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

    def test_stripping_latex_comment_preserves_newline(self):
        self.assertEqual(
            self.mod._strip_latex_comment(r'\newcommand{\foo}{%' + '\n'),
            r'\newcommand{\foo}{% ' + '\n')

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

    def test_multi_panel_figure_counts_once_with_combined_aspect(self):
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
                    pathlib.Path('panel-a.png').touch()
                    pathlib.Path('panel-b.png').touch()
                    with contextlib.redirect_stdout(io.StringIO()):
                        words = self.mod.count_figures_words([
                            r'\begin{figure}' + '\n',
                            r'\includegraphics{panel-a}' + '\n',
                            r'\includegraphics{panel-b}' + '\n',
                            r'\caption{Caption text.}' + '\n',
                            r'\end{figure}' + '\n',
                        ], opts)

            self.assertEqual(words, 76)
            self.assertEqual(calls, ['panel-a.png', 'panel-b.png'])
        finally:
            self.mod._parse_identify_dimensions = old_parse

    def test_pdf_figures_use_pymupdf_dimensions(self):
        opts = type('Opts', (), {
            'var': None,
            'figs': 'identify',
            'scale_figs': 1.0,
        })()

        old_pdf = self.mod._parse_pdf_dimensions
        old_identify = self.mod._parse_identify_dimensions
        try:
            pdf_calls = []
            identify_calls = []
            self.mod._parse_pdf_dimensions = (
                lambda filename: (pdf_calls.append(filename), (200.0, 100.0))[1])
            self.mod._parse_identify_dimensions = (
                lambda filename: (identify_calls.append(filename), (640.0, 480.0))[1])

            with tempfile.TemporaryDirectory() as tmpdir:
                with pushd(tmpdir):
                    pathlib.Path('plot.pdf').touch()
                    with contextlib.redirect_stdout(io.StringIO()):
                        words = self.mod.count_figures_words([
                            r'\begin{figure}' + '\n',
                            r'\includegraphics{plot}' + '\n',
                            r'\end{figure}' + '\n',
                        ], opts)

            self.assertEqual(words, 95)
            self.assertEqual(pdf_calls, ['plot.pdf'])
            self.assertEqual(identify_calls, [])
        finally:
            self.mod._parse_pdf_dimensions = old_pdf
            self.mod._parse_identify_dimensions = old_identify

    def test_pdf_figures_fall_back_to_gs_without_pymupdf(self):
        old_import = builtins.__import__
        old_gs = self.mod._parse_gs_dimensions
        old_warned = self.mod.PYMUPDF_MISSING_WARNED
        try:
            def fake_import(name, *args, **kwargs):
                if name == 'fitz':
                    raise ImportError('no fitz')
                return old_import(name, *args, **kwargs)

            calls = []
            builtins.__import__ = fake_import
            self.mod.PYMUPDF_MISSING_WARNED = False
            self.mod._parse_gs_dimensions = (
                lambda filename: (calls.append(filename), (300.0, 100.0))[1])

            with contextlib.redirect_stdout(io.StringIO()) as output:
                dimensions = self.mod._parse_pdf_dimensions('plot.pdf')

            self.assertEqual(dimensions, (300.0, 100.0))
            self.assertEqual(calls, ['plot.pdf'])
            self.assertIn('*** WARNING: PyMuPDF is not installed ***',
                          output.getvalue())
            self.assertIn('falling back to Ghostscript', output.getvalue())
        finally:
            builtins.__import__ = old_import
            self.mod._parse_gs_dimensions = old_gs
            self.mod.PYMUPDF_MISSING_WARNED = old_warned

    def test_tikz_figure_raises_instead_of_counting_words(self):
        opts = type('Opts', (), {
            'var': None,
            'figs': 'identify',
            'scale_figs': 1.0,
        })()

        with self.assertRaisesRegex(ValueError, 'TikZ figure.*PDF'):
            self.mod.count_figures_words([
                r'\begin{figure}' + '\n',
                r'\begin{tikzpicture}' + '\n',
                r'\draw (0,0) -- (1,1);' + '\n',
                r'\end{tikzpicture}' + '\n',
                r'\end{figure}' + '\n',
            ], opts)

    def test_input_tikz_figure_raises(self):
        opts = type('Opts', (), {
            'var': None,
            'figs': 'identify',
            'scale_figs': 1.0,
        })()

        with tempfile.TemporaryDirectory() as tmpdir:
            with pushd(tmpdir):
                pathlib.Path('tikz-figure.tex').write_text(
                    r'\begin{tikzpicture}' + '\n' +
                    r'\draw (0,0) -- (1,1);' + '\n' +
                    r'\end{tikzpicture}' + '\n')

                with self.assertRaisesRegex(ValueError, 'tikz-figure.tex'):
                    self.mod.count_figures_words([
                        r'\begin{figure}' + '\n',
                        r'\input{tikz-figure}' + '\n',
                        r'\end{figure}' + '\n',
                    ], opts)

    def test_starred_includegraphics_with_repeated_options(self):
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
                    pathlib.Path('panel.png').touch()
                    with contextlib.redirect_stdout(io.StringIO()):
                        words = self.mod.count_figures_words([
                            r'\begin{figure}' + '\n',
                            r'\includegraphics*[draft][width=0.5\textwidth]{panel}' + '\n',
                            r'\end{figure}' + '\n',
                        ], opts)

            self.assertEqual(words, 132)
            self.assertEqual(calls, ['panel.png'])
        finally:
            self.mod._parse_identify_dimensions = old_parse

    def test_includegraphics_outside_figure_is_ignored(self):
        opts = type('Opts', (), {
            'var': None,
            'figs': 'identify',
            'scale_figs': 1.0,
        })()

        with contextlib.redirect_stdout(io.StringIO()) as output:
            words = self.mod.count_figures_words([
                r'\newcommand{\tablefigureicon}[1]{%' + '\n',
                r'  \includegraphics{figures/#1.pdf}%' + '\n',
                r'}' + '\n',
            ], opts)

        self.assertEqual(words, 0)
        self.assertIn('outside figure environment', output.getvalue())

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
