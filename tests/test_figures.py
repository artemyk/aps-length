import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from aps_length import figures, tex, tools
from tests.helpers import options


class FigureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.opts = options('--scale-figs=1')

    def count(self, source, dimensions=(640.0, 480.0)):
        with patch.object(tools, 'figure_dimensions', return_value=dimensions) as measure:
            with contextlib.redirect_stdout(io.StringIO()):
                count = figures.count_figures_words(tex.ParsedSource(source), self.opts, self.directory)
        return count, measure

    def test_multiline_filename_with_spaces(self):
        (self.directory / 'fig with space.png').touch()
        count, measure = self.count('\\begin{figure}\n\\includegraphics{fig with\n space}\n\\end{figure}')
        self.assertEqual(count, 132)
        self.assertEqual(measure.call_args.args[0], self.directory / 'fig with space.png')

    def test_multi_panel_figure_counts_once(self):
        for name in ('a.png', 'b.png'):
            (self.directory / name).touch()
        source = r'\begin{figure}\includegraphics{a}\includegraphics{b}\end{figure}'
        count, measure = self.count(source)
        self.assertEqual(count, 76)
        self.assertEqual(measure.call_count, 2)

    def test_explicit_row_break_stacks_panels(self):
        (self.directory / 'a.png').touch()
        source = r'\begin{figure}\includegraphics{a}\\\includegraphics{a}\end{figure}'
        count, measure = self.count(source)
        self.assertEqual(count, 245)
        self.assertEqual(measure.call_count, 1)

    def test_comments_and_parbox_do_not_force_new_row(self):
        (self.directory / 'a.png').touch()
        for between in ('% ignored \\\\\n', r'\parbox{1cm}{label}', '\n'):
            with self.subTest(between=between):
                source = (r'\begin{figure}\includegraphics{a}' + between +
                          r'\includegraphics{a}\end{figure}')
                self.assertEqual(self.count(source)[0], 76)

    def test_two_figures_on_same_line_do_not_share_panels(self):
        (self.directory / 'a.png').touch()
        source = (r'\begin{figure}\includegraphics{a}\end{figure}'
                  r'\begin{figure*}\includegraphics{a}\end{figure*}')
        self.assertEqual(self.count(source)[0], 622)

    def test_graphics_outside_float_are_ignored(self):
        with contextlib.redirect_stderr(io.StringIO()) as errors:
            count, measure = self.count(r'\newcommand{\icon}[1]{\includegraphics{figures/#1.pdf}}')
        self.assertEqual(count, 0)
        measure.assert_not_called()
        self.assertIn('outside figure environment', errors.getvalue())

    def test_filename_extension_precedence_and_directory_rejection(self):
        (self.directory / 'plot.pdf').touch()
        (self.directory / 'plot.png').touch()
        with contextlib.redirect_stderr(io.StringIO()) as errors:
            self.assertEqual(figures.resolve_figure_filename('plot', self.directory),
                             self.directory / 'plot.pdf')
        self.assertIn('multiple picture files', errors.getvalue())
        (self.directory / 'folder.png').mkdir()
        with self.assertRaises(FileNotFoundError):
            figures.resolve_figure_filename('folder', self.directory)

    def test_variables_and_escaped_filename_characters(self):
        (self.directory / 'fig%name.png').touch()
        self.opts.var = [(r'\dir', 'wrong'), (r'\directory', str(self.directory))]
        source = r'\begin{figure}\includegraphics{\directory/fig\%name.png}\end{figure}'
        count, _ = self.count(source)
        self.assertEqual(count, 132)

    def test_unresolved_variable_is_a_clear_error(self):
        with self.assertRaisesRegex(ValueError, 'Unresolved TeX.*--var'):
            self.count(r'\begin{figure}\includegraphics{\unknown/plot}\end{figure}')

    def test_inline_tikz_rejected_but_commented_tikz_ignored(self):
        with self.assertRaisesRegex(ValueError, 'TikZ figure.*PDF'):
            self.count(r'\begin{figure}\begin{tikzpicture}a\end{tikzpicture}\end{figure}')
        self.assertEqual(self.count('\\begin{figure}\n% \\tikz ignored\n\\end{figure}')[0], 0)

    def test_nested_tikz_input_resolves_relative_to_main_directory(self):
        (self.directory / 'parts').mkdir()
        (self.directory / 'parts' / 'a.tex').write_text(r'\input{b}')
        (self.directory / 'b.tex').write_text(r'\begin{tikzpicture}x\end{tikzpicture}')
        with self.assertRaisesRegex(ValueError, 'b.tex'):
            self.count(r'\begin{figure}\input{parts/a}\end{figure}')

    def test_input_cycles_and_symlink_aliases_terminate(self):
        (self.directory / 'a.tex').write_text(r'\input{alias}')
        (self.directory / 'alias.tex').symlink_to('a.tex')
        self.assertIsNone(figures.find_tikz_input(r'\input{a}', self.directory))

    def test_repeated_pdf_uses_pdf_backend_even_with_identify(self):
        (self.directory / 'plot.pdf').touch()
        with patch.object(tools, 'pdf_dimensions', return_value=(200.0, 100.0)) as pdf:
            with patch.object(tools, 'identify_dimensions') as identify:
                with contextlib.redirect_stdout(io.StringIO()):
                    count = figures.count_figures_words(
                        tex.ParsedSource(r'\begin{figure}\includegraphics{plot}\end{figure}'), self.opts, self.directory)
        self.assertEqual(count, 95)
        pdf.assert_called_once()
        identify.assert_not_called()

    def test_invalid_or_overflowing_combined_dimensions_are_errors(self):
        (self.directory / 'a.png').touch()
        source = r'\begin{figure}\includegraphics{a}\end{figure}'
        for dimensions in ((0.0, 1.0), (1e308, 1e-308), (1e-308, 1e308)):
            with self.subTest(dimensions=dimensions), self.assertRaises(ValueError):
                self.count(source, dimensions)
        self.opts.scale_figs = 1e308
        with self.assertRaisesRegex(ValueError, 'overflowed'):
            self.count(source)
