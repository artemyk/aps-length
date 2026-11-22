import contextlib
import io
import random
import unittest

from aps_length import counting, tex
from tests.helpers import document


class CommentTests(unittest.TestCase):
    def test_stop_marker_requires_real_comment(self):
        for prefix, expected in [('', False), ('%', True), ('text %', True),
                                 (r'text \%', False), (r'text \\%', True),
                                 (r'text \\\%', False)]:
            with self.subTest(prefix=prefix):
                self.assertEqual(tex.has_stop_comment(prefix + '!STOP!', '!STOP!'), expected)
        self.assertFalse(tex.has_stop_comment('% !STOP!', ''))

    def test_stripping_preserves_comment_semantics_and_newline(self):
        for newline in ('\n', '\r\n', '\r', ''):
            with self.subTest(newline=newline):
                self.assertEqual(tex.strip_latex_comment(r'\newcommand{\foo}{%' + newline),
                                 r'\newcommand{\foo}{% ' + newline)
        self.assertEqual(tex.strip_latex_comment(r'10\% text'), r'10\% text')

    def test_mask_preserves_every_offset(self):
        source = 'before % ignored\r\nnext \\% kept\n'
        masked = tex.mask_comments(source)
        self.assertEqual(len(source), len(masked))
        self.assertEqual(masked.index('next'), source.index('next'))
        self.assertNotIn('ignored', masked)
        self.assertIn(r'\% kept', masked)


class EnvironmentTests(unittest.TestCase):
    def test_environment_selection_respects_containment_and_outermost(self):
        source = (r'\begin{table}\begin{tabular}{c}a'
                  r'\begin{tabular}{c}b\end{tabular}\end{tabular}\end{table}'
                  r'\begin{tabular}{c}outside\end{tabular}')
        document = tex.ParsedSource(source)
        table = document.find_environments(('table',))[0]
        self.assertEqual(len(document.find_environments(('tabular',))), 3)
        self.assertEqual(len(document.find_environments(('tabular',), within=table)), 2)
        selected = document.find_environments(('tabular',), within=table, outermost=True)
        self.assertEqual(len(selected), 1)
        self.assertNotIn('outside', source[selected[0].body_start:selected[0].body_end])

    def test_crossed_environments_cannot_be_hidden_by_name_selection(self):
        source = r'\begin{figure}\begin{custom}x\end{figure}\end{custom}'
        with self.assertRaisesRegex(ValueError, r'Unmatched \\end\{figure\}'):
            tex.ParsedSource(source)

    def test_rows_keep_nested_environments_and_source_ranges(self):
        source = r'a&\begin{matrix}b\\c\end{matrix}\\*[2pt]d&e\\'
        document = tex.ParsedSource(source)
        rows = list(tex.iter_rows(document))
        self.assertEqual(len(rows), 2)
        self.assertEqual([span.name for span in rows[0].environments], ['matrix'])
        self.assertEqual(source[rows[1].start:rows[1].end], 'd&e')
        self.assertEqual(rows[1].environments, ())

    def test_same_line_environments_have_distinct_spans(self):
        source = r'\begin{figure}a\end{figure}\begin{figure*}b\end{figure*}'
        spans = tex.ParsedSource(source).find_environments(('figure',))
        self.assertEqual([source[s.body_start:s.body_end] for s in spans], ['a', 'b'])
        self.assertEqual([s.name for s in spans], ['figure', 'figure*'])

    def test_exact_names_and_comments(self):
        source = (r'% \begin{table}' + '\n' +
                  r'\begin{tabular}{c}a\end{tabular}' + '\n' +
                  r'\begin{tableau}b\end{tableau}')
        self.assertEqual(tex.ParsedSource(source).find_environments(('table',)), [])

    def test_whitespace_and_multiline_commands(self):
        source = '\\begin \n{abstract}text\\end {abstract}'
        self.assertEqual(len(tex.ParsedSource(source).find_environments(('abstract',))), 1)

    def test_malformed_environments_are_errors(self):
        for source in (r'\begin{figure}no end', r'\end{figure}',
                       r'\begin{figure}\end{figure*}',
                       r'\begin{a}\begin{b}\end{a}\end{b}'):
            with self.subTest(source=source), self.assertRaises(ValueError):
                tex.ParsedSource(source).find_environments(('figure', 'a', 'b'))

    def test_blank_nested_spans_preserves_surrounding_text(self):
        source = 'before' + r'\begin{align}x\begin{split}a\end{split}\end{align}' + 'after'
        spans = tex.ParsedSource(source).find_environments(('align', 'split'))
        result = tex.blank_spans(source, [(s.start, s.end) for s in spans])
        self.assertEqual(result.split(), ['before', 'after'])
        self.assertEqual(len(result), len(source))


class PreprocessTests(unittest.TestCase):
    def test_all_display_delimiters_on_same_line(self):
        source = tex.normalize_display_math(r'$$a$$ and \[b\] and $$c$$')
        self.assertEqual(len(tex.ParsedSource(source).find_environments(('equation',))), 3)

    def test_escaped_dollars_and_commented_delimiters_are_ignored(self):
        source = r'\$\$ literals % $$ ignored' + '\n'
        self.assertEqual(tex.normalize_display_math(source), source)

    def test_invalid_display_delimiters_are_errors(self):
        for source in ('$$a', r'\[a', r'\]a', r'$$a\]', r'\[a$$'):
            with self.subTest(source=source), self.assertRaises(ValueError):
                tex.normalize_display_math(source)

    def test_appendix_and_bibliography_preserve_same_line_text(self):
        for command in (r'\appendix', r'\bibliography {references}'):
            with self.subTest(command=command):
                result = tex.preprocess('before ' + command + ' excluded')
                self.assertIn('before ', result)
                self.assertNotIn('excluded', result)
                self.assertTrue(result.endswith('\\end{document}\n'))
        self.assertIn('kept', tex.preprocess(r'\appendix kept', appendix=True))

    def test_stop_comment_can_be_disabled(self):
        source = 'before\n% !STOP-APS-LENGTH!\nafter\n'
        self.assertNotIn('after', tex.preprocess(source))
        self.assertIn('after', tex.preprocess(source, stop_comment=''))

    def test_commented_stop_commands_and_end_of_document(self):
        source = '% \\appendix\nbefore \\end{document} after'
        self.assertIn('before', tex.preprocess(source))
        self.assertNotIn('after', tex.preprocess(source))

    def test_documentclass_options_support_multiline_and_no_duplicates(self):
        source = '% \\documentclass{ignored}\n\\documentclass\n[twocolumn,\nnofootinbib]{revtex4-2}'
        result = tex.add_documentclass_option(source, 'nofootinbib')
        self.assertEqual(result.count('nofootinbib'), 1)
        self.assertTrue(result.startswith('% \\documentclass{ignored}\n'))


class GraphicsParsingTests(unittest.TestCase):
    def test_multiline_starred_command_with_nested_options(self):
        source = r'\includegraphics*[draft][width={0.5\textwidth},extra={a[b]}]{fig with' + '\n space}'
        self.assertEqual(tex.includegraphics_commands(source)[0].filename, 'fig with space')

    def test_preserves_multiple_spaces_and_nested_filename_braces(self):
        self.assertEqual(tex.includegraphics_commands(r'\includegraphics{a  b.png}')[0].filename,
                         'a  b.png')
        self.assertEqual(tex.includegraphics_commands(r'\includegraphics{\dir{}/a}')[0].filename,
                         r'\dir{}/a')

    def test_comment_continuation_and_literal_percent(self):
        source = '\\includegraphics% comment\n{a\\%b.png}'
        self.assertEqual(tex.includegraphics_commands(source)[0].filename, r'a\%b.png')
        self.assertEqual(tex.includegraphics_commands('% \\includegraphics{ignored}\n'), [])
        self.assertEqual(tex.includegraphics_commands('\\includegraphics{figure% }ignored\n.png}')[0].filename,
                         'figure.png')

    def test_unbalanced_arguments_are_errors(self):
        for source in (r'\includegraphics{unfinished', r'\includegraphics[width={a]}{b}',
                       r'\includegraphics file'):
            with self.subTest(source=source), self.assertRaises(ValueError):
                tex.includegraphics_commands(source)


class CountingTests(unittest.TestCase):
    def test_ignored_content_is_removed_before_parsing_graphics(self):
        source = document(r'\begin{custom}\includegraphics unparseable\end{custom} kept')
        filtered = counting.wordcount_source(tex.ParsedSource(source), ('custom',))
        self.assertNotIn('includegraphics', filtered)
        self.assertIn('kept', filtered)
        self.assertEqual(len(filtered), len(source))

    def test_command_acknowledgments_preserve_document_end_and_offsets(self):
        source = document(r'kept \acknowledgments excluded')
        filtered = counting.wordcount_source(tex.ParsedSource(source), tex.DEFAULT_IGNORE_ENVS)
        self.assertIn('kept', filtered)
        self.assertNotIn('excluded', filtered)
        self.assertIn(r'\end{document}', filtered)
        self.assertEqual(len(filtered), len(source))

    def test_nested_row_heights_combine_without_recounting_environments(self):
        source = (r'\begin{equation}\begin{aligned}a=b\\'
                  r'c=\begin{pmatrix}1\\2\\3\end{pmatrix}'
                  r'\end{aligned}\end{equation}')
        self.assertEqual(counting.count_equations_words(tex.ParsedSource(source)), 64)

    def test_many_adjacent_nested_environments(self):
        panel = r'x=\begin{pmatrix}a\\b\end{pmatrix}'
        source = r'\\'.join([panel] * 1000)
        self.assertEqual(counting.logical_rows(tex.ParsedSource(source)), 2000)

    def test_unbalanced_row_groups_are_reported(self):
        for source in ('{a&b', 'a}&b'):
            with self.subTest(source=source), self.assertRaisesRegex(ValueError, 'brace in row'):
                counting.logical_rows(tex.ParsedSource(source))

    def test_escaped_braces_and_rule_names_after_row_breaks(self):
        self.assertEqual(counting.logical_rows(tex.ParsedSource(r'\{a\}&b\\')), 1)
        self.assertEqual(counting.logical_rows(tex.ParsedSource(r'a\\hline\\')), 2)

    def test_inline_abstract_and_comments(self):
        self.assertEqual(counting.count_chars_abstract(tex.ParsedSource(document(abstract='abc'))), 3)
        source = '\\begin{abstract}\nabc% ignored\ndef\n\\end{abstract}'
        self.assertEqual(counting.count_chars_abstract(tex.ParsedSource(source)), 6)

    def test_missing_or_multiple_abstracts_are_errors(self):
        with self.assertRaisesRegex(ValueError, r'\\begin\{abstract\}'):
            counting.count_chars_abstract(tex.ParsedSource(r'\documentclass{revtex4-2}'))
        with self.assertRaisesRegex(ValueError, 'multiple'):
            counting.count_chars_abstract(tex.ParsedSource(r'\begin{abstract}a\end{abstract}' * 2))

    def test_maketitle_preserves_same_line_body_text(self):
        source = counting.wordcount_source(tex.ParsedSource(document('keep these words')), tex.DEFAULT_IGNORE_ENVS)
        self.assertIn('keep these words', source)
        self.assertNotIn(r'\maketitle', source)

    def test_table_text_is_filtered_but_caption_is_retained(self):
        table = r'\begin{table}\begin{tabular}{cc}excluded&cells\\\end{tabular}\caption{Keep caption}\end{table}'
        source = counting.wordcount_source(tex.ParsedSource(document(table)), tex.DEFAULT_IGNORE_ENVS)
        self.assertNotIn('excluded', source)
        self.assertIn('Keep caption', source)

    def test_custom_ignored_environments_apply(self):
        source = counting.wordcount_source(tex.ParsedSource(document(r'\begin{custom}excluded\end{custom} kept')),
                                           (*tex.DEFAULT_IGNORE_ENVS, 'custom'))
        self.assertNotIn('excluded', source)
        self.assertIn('kept', source)

    def test_multiple_equations_and_widetext_on_same_line(self):
        source = (r'\begin{widetext}\begin{equation}a\end{equation}\end{widetext}'
                  r'\begin{equation*}b\end{equation*}')
        self.assertEqual(counting.count_equations_words(tex.ParsedSource(source)), 48)

    def test_equation_rows_count_separators_not_source_lines(self):
        source = r'\begin{align}a\\b\\[2pt]c\\\end{align}'
        self.assertEqual(counting.count_equations_words(tex.ParsedSource(source)), 48)

    def test_nested_matrix_sets_row_height(self):
        source = r'\begin{equation}\begin{array}[t]{cc}a&b\\c&d\end{array}\end{equation}'
        self.assertEqual(counting.count_equations_words(tex.ParsedSource(source)), 32)

    def test_braced_row_breaks_and_comments_are_not_top_level_rows(self):
        self.assertEqual(counting.logical_rows(tex.ParsedSource(r'\makecell{a\\b}&c\\')), 1)
        self.assertEqual(counting.logical_rows(tex.ParsedSource('a% \\\\ ignored\n&b\\\\')), 1)

    def test_table_is_not_double_counted_as_tabular(self):
        table = r'\begin{table}\begin{tabular}{cc}\hline a&b\\ c&d\\\hline\end{tabular}\end{table}'
        self.assertEqual(counting.count_tables_words(tex.ParsedSource(table)), 26)

    def test_two_column_table_rules_and_optional_spacing(self):
        table = r'\begin{table*}\begin{tabular*}{\textwidth}[t]{cc}\toprule a&b\\[2pt]\midrule c&d\\\bottomrule\end{tabular*}\end{table*}'
        self.assertEqual(counting.count_tables_words(tex.ParsedSource(table)), 52)

    def test_empty_or_unsupported_table_reports_error(self):
        with self.assertRaisesRegex(ValueError, 'no supported tabular rows'):
            counting.count_tables_words(tex.ParsedSource(r'\begin{table}\caption{Only a caption}\end{table}'))

    def test_unterminated_math_and_table_are_errors(self):
        with self.assertRaises(ValueError):
            counting.count_equations_words(tex.ParsedSource(r'\begin{align}a\\b'))
        with self.assertRaises(ValueError):
            counting.count_tables_words(tex.ParsedSource(r'\begin{table}a'))

    def test_table_row_counts_under_reproducible_format_variations(self):
        rng = random.Random(3107)
        for case in range(100):
            rows = rng.randint(1, 8)
            separator = rng.choice([r'\\', '\\\\\n', '\\\\% ignored\n', r'\\[2pt]'])
            body = separator.join('a&b' for _ in range(rows))
            if rng.choice([False, True]):
                body += separator
            body = r'\toprule ' + body + r'\bottomrule'
            source = r'\begin{table}\begin{tabular}{cc}' + body + r'\end{tabular}\end{table}'
            with self.subTest(case=case, rows=rows), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(counting.count_tables_words(tex.ParsedSource(source)), int(6.5 * rows + 13))
