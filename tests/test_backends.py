import contextlib
import io
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from aps_length import counting, tex, tools
from tests.helpers import document, options


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.workspaces = []

    def fake_latex(self, command, **kwargs):
        output = next((part.split('=', 1)[1] for part in command
                       if part.startswith('-output-directory=')), None)
        if output:
            output = Path(output)
            self.workspaces.append(output)
            self.assertNotEqual(output, self.directory)
            target = Path(command[-1]).stem
            if target == 'manuscript':
                (output / 'manuscript.aux').write_text('')
                (output / 'manuscriptNotes.bib').write_text('notes')
            (output / (target + '.log')).write_bytes(b'3.08633\n3.08635\nother\n')
        return subprocess.CompletedProcess(command, 0, b'', b'')

    def test_wordcount_without_bibliography_skips_bibtex(self):
        with patch.object(tools, 'run_command', side_effect=self.fake_latex) as run:
            count = counting.count_main_text_words_wordcount(tex.ParsedSource(document('body')), options(), self.directory)
        self.assertEqual(count, 2)
        self.assertEqual(run.call_count, 4)
        self.assertTrue(all(not path.exists() for path in self.workspaces))
        self.assertEqual(list(self.directory.iterdir()), [])
        self.assertTrue(all('-synctex=1' in call.args[0] for call in run.call_args_list))
        self.assertTrue(run.call_args.kwargs['input_text'].endswith('manuscript.tex\n'))

    def test_wordcount_runs_bibtex_when_aux_requires_it(self):
        def with_bibliography(command, **kwargs):
            result = self.fake_latex(command, **kwargs)
            if command[0] != 'bibtex':
                (self.workspaces[-1] / 'manuscript.aux').write_text(
                    r'\citation{ref}\bibdata{refs}\bibstyle{plain}')
            return result

        with patch.object(tools, 'run_command', side_effect=with_bibliography) as run:
            counting.count_main_text_words_wordcount(tex.ParsedSource(document()), options(), self.directory)
        bibtex = [call for call in run.call_args_list if call.args[0][0] == 'bibtex']
        self.assertEqual(len(bibtex), 1)
        self.assertEqual(bibtex[0].kwargs['cwd'], self.workspaces[0])
        self.assertTrue(bibtex[0].kwargs['env']['BIBINPUTS'].startswith(str(self.directory)))

    def test_latex_failure_cleans_workspace_and_reports_text_output(self):
        def failure(command, **kwargs):
            self.fake_latex(command, **kwargs)
            return subprocess.CompletedProcess(command, 1, 'latex stdout', 'latex stderr')

        sentinel = self.directory / 'aps_length_userNotes.bib'
        sentinel.write_text('keep')
        with patch.object(tools, 'run_command', side_effect=failure):
            with self.assertRaisesRegex(RuntimeError, 'LaTeX error.*') as error:
                counting.count_main_text_words_wordcount(tex.ParsedSource(document()), options(), self.directory)
        self.assertIn('latex stderr', str(error.exception))
        self.assertTrue(all(not path.exists() for path in self.workspaces))
        self.assertEqual(sentinel.read_text(), 'keep')

    def test_resource_copy_failure_cleans_partially_created_workspace(self):
        paths = []
        make_directory = tempfile.mkdtemp

        def create_directory(**kwargs):
            path = make_directory(**kwargs)
            paths.append(Path(path))
            return path

        with patch.object(Path, 'write_bytes', side_effect=OSError('disk full')):
            with patch.object(tools.tempfile, 'mkdtemp', side_effect=create_directory):
                with self.assertRaisesRegex(OSError, 'disk full'):
                    counting.count_main_text_words_wordcount(tex.ParsedSource(document()), options(), self.directory)
        self.assertEqual(len(paths), 1)
        self.assertFalse(paths[0].exists())
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_ignoreerrors_still_requires_count_log(self):
        def failure(command, **kwargs):
            return subprocess.CompletedProcess(command, 1, b'failure', b'')

        with patch.object(tools, 'run_command', side_effect=failure):
            with contextlib.redirect_stderr(io.StringIO()) as errors:
                with self.assertRaisesRegex(RuntimeError, 'did not produce a word-count log'):
                    counting.count_main_text_words_wordcount(
                        tex.ParsedSource(document()), options('--ignoreerrors'), self.directory)
        self.assertIn('continuing', errors.getvalue())

    def test_detex_filters_title_equations_tables_and_custom_environments(self):
        body = (r'kept \begin{equation}excludedmath\end{equation}'
                r'\begin{custom}excludedcustom\end{custom}'
                r'\begin{table}\begin{tabular}{c}excludedcell\end{tabular}'
                r'\caption{caption}\end{table}')

        def detex(command, **kwargs):
            source = Path(command[-1]).read_text()
            for excluded in ('excludedmath', 'excludedcustom', 'excludedcell', 'A title', 'An abstract'):
                self.assertNotIn(excluded, source)
            self.assertIn('kept', source)
            self.assertIn('caption', source)
            return subprocess.CompletedProcess(command, 0, b'kept steady-state caption\n', b'')

        opts = options('--env=' + ','.join((*counting.tex.DEFAULT_IGNORE_ENVS, 'custom')))
        with patch.object(tools, 'run_command', side_effect=detex):
            self.assertEqual(counting.count_main_text_words_detex(tex.ParsedSource(document(body)), opts, self.directory), 4)

    def test_detex_failure_cleans_workspace(self):
        paths = []

        def failure(command, **kwargs):
            paths.append(Path(command[-1]).parent)
            raise RuntimeError('detex failed')

        with patch.object(tools, 'run_command', side_effect=failure):
            with self.assertRaisesRegex(RuntimeError, 'detex failed'):
                counting.count_main_text_words_detex(tex.ParsedSource(document()), options(), self.directory)
        self.assertFalse(paths[0].exists())


def has_revtex():
    if not shutil.which('pdflatex') or not shutil.which('kpsewhich'):
        return False
    return subprocess.run(['kpsewhich', 'revtex4-2.cls'], capture_output=True,
                          timeout=10).returncode == 0


@unittest.skipUnless(has_revtex(), 'pdflatex or REVTeX is unavailable')
class LatexIntegrationTests(unittest.TestCase):
    def test_real_latex_without_bibliography_counts_body_only_and_cleans_up(self):
        with tempfile.TemporaryDirectory(prefix='aps length test ') as directory:
            directory = Path(directory)
            source = document('Main body has five words.')
            count = counting.count_main_text_words_wordcount(tex.ParsedSource(source), options(), directory)
            self.assertEqual(count, 5)
            self.assertEqual(list(directory.iterdir()), [])

    def test_real_latex_counts_caption_but_not_table_cells(self):
        source = document(r'\begin{table}\begin{tabular}{cc}cell&cell\\cell&cell\\'
                          r'\end{tabular}\caption{Three caption words.}\end{table}')
        with tempfile.TemporaryDirectory() as directory:
            # REVTeX's generated table label contributes one additional word.
            self.assertEqual(counting.count_main_text_words_wordcount(tex.ParsedSource(source), options(), Path(directory)), 4)

    def test_real_latex_resolves_inputs_from_manuscript_directory(self):
        with tempfile.TemporaryDirectory(prefix='aps length test ') as directory:
            directory = Path(directory)
            (directory / 'body.tex').write_text('These are four words.\n\n')
            count = counting.count_main_text_words_wordcount(
                tex.ParsedSource(document(r'\input{body}')), options(), directory)
            self.assertEqual(count, 4)
            self.assertEqual([path.name for path in directory.iterdir()], ['body.tex'])

    def test_real_latex_keeps_footnotes(self):
        with tempfile.TemporaryDirectory() as directory:
            count = counting.count_main_text_words_wordcount(
                tex.ParsedSource(document(r'Main text.\footnote{Two words.}')), options(), Path(directory))
            # The generated footnote label contributes an additional word.
            self.assertEqual(count, 5)


@unittest.skipUnless(shutil.which('detex'), 'detex is unavailable')
class DetexIntegrationTests(unittest.TestCase):
    def test_real_detex_preserves_same_line_body_and_caption(self):
        source = document(r'Four ordinary body words. \begin{equation}x=y\end{equation}'
                          r'\begin{table}\begin{tabular}{c}excluded\\\end{tabular}'
                          r'\caption{Two words.}\end{table}')
        with tempfile.TemporaryDirectory() as directory:
            count = counting.count_main_text_words_detex(tex.ParsedSource(source), options(), Path(directory))
            self.assertEqual(count, 6)
