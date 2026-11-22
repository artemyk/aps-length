"""Command-line options and manuscript-level reporting."""

import argparse
from dataclasses import dataclass
import math
from pathlib import Path
import shlex
import sys

from . import counting, figures, tex, tools


# Historical limits from the original tool (2017-10-03). Keep the estimate
# separate from journal policy: consult APS before relying on these limits.
WORD_LIMITS = {
    'PRL': 3750, 'PRX': 20000, 'RMP': 50000, 'RMP-COL': 20000,
    'PRA-RC': 4500, 'PRB-RC': 3500, 'PRC-RC': 4500, 'PRD-RC': 4500,
    'PRE-RC': 4500, 'PRApplied': 3500, 'PRST-PER': 3500,
}


@dataclass(frozen=True)
class Counts:
    abstract_chars: int
    main_text: int
    equations: int
    figures: int
    tables: int

    @property
    def total(self):
        return self.main_text + self.equations + self.figures + self.tables


def nonnegative_float(value):
    try:
        number = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError('must be a finite nonnegative number') from error
    if not math.isfinite(number) or number < 0:
        raise argparse.ArgumentTypeError('must be a finite nonnegative number')
    return number


def positive_float(value):
    number = nonnegative_float(value)
    if not number:
        raise argparse.ArgumentTypeError('must be greater than zero')
    return number


def build_parser():
    parser = argparse.ArgumentParser(description='Estimate the length of APS LaTeX manuscripts.')
    parser.add_argument('tex_files', nargs='+', type=Path, metavar='tex-file')
    parser.add_argument('-v', '--var', nargs=2, action='append', metavar=('KEY', 'VALUE'),
                        help='substitute literal TeX variables in figure filenames')
    parser.add_argument('-e', '--env', default=','.join(tex.DEFAULT_IGNORE_ENVS),
                        help='comma-separated environments to omit from the text count')
    parser.add_argument('-x', '--appendix', action='store_true',
                        help=r'include text after \appendix')
    parser.add_argument('--stop-comment', default=tex.DEFAULT_STOP_COMMENT, metavar='TEXT',
                        help='stop at a comment containing TEXT; empty disables (default: %(default)s)')
    parser.add_argument('-m', '--method', choices=('detex', 'wordcount'), default='wordcount',
                        help='main-text backend (default: %(default)s)')
    parser.add_argument('-f', '--figs', choices=('identify', 'gs'), default='identify',
                        help='non-PDF figure backend (default: %(default)s); PDFs prefer PyMuPDF')
    parser.add_argument('--scale-figs', type=nonnegative_float, default=1.1,
                        help='multiply the figure estimate by this factor (default: %(default)s)')
    parser.add_argument('-j', '--journal', choices=('None', *WORD_LIMITS), default='None',
                        help='compare against a historical journal limit')
    parser.add_argument('-l', '--latex', default='pdflatex', help='LaTeX command (default: %(default)s)')
    parser.add_argument('-o', '--latexopts', default='-halt-on-error',
                        help='quoted LaTeX options (default: %(default)s)')
    parser.add_argument('-i', '--ignoreerrors', action='store_true',
                        help='attempt to count even after a LaTeX/BibTeX error')
    parser.add_argument('--keep_tmp_files', '--keep-tmp-files', action='store_true',
                        help='retain the temporary directory and print its path')
    parser.add_argument('--timeout', type=positive_float, default=tools.DEFAULT_TIMEOUT,
                        help='timeout in seconds per external command (default: %(default)s)')
    return parser


def validate_options(parser, opts):
    try:
        if not shlex.split(opts.latex):
            parser.error('--latex must name an executable')
        shlex.split(opts.latexopts)
    except ValueError as error:
        parser.error('invalid command quoting: %s' % error)
    if any(not key for key, _ in opts.var or ()):
        parser.error('--var keys must not be empty')
    opts.env = tuple(env.strip() for env in opts.env.split(',') if env.strip())


def process(tex_file, opts):
    path = Path(tex_file).resolve()
    directory = path.parent
    print('Processing TeX file: %s\n' % path)
    document = tex.ParsedSource(tex.preprocess(path.read_text(encoding='utf-8'),
                                              appendix=opts.appendix,
                                              stop_comment=opts.stop_comment))
    abstract = counting.count_chars_abstract(document)
    # Check unsupported/invalid structures before starting expensive LaTeX runs.
    equations = counting.count_equations_words(document)
    tables = counting.count_tables_words(document)
    figure_words = figures.count_figures_words(document, opts, directory)
    if opts.method == 'wordcount':
        main_text = counting.count_main_text_words_wordcount(document, opts, directory)
    else:
        main_text = counting.count_main_text_words_detex(document, opts, directory)
    counts = Counts(abstract, main_text, equations, figure_words, tables)
    print('\nAbstract:       %6d chars (source estimate; max 600)' % counts.abstract_chars)
    print('Main text:      %6d words' % counts.main_text)
    print('Displayed Math: %6d words' % counts.equations)
    print('Figures:        %6d words' % counts.figures)
    print('Tables:         %6d words' % counts.tables)
    print('TOTAL:          %6d words\n' % counts.total)
    if opts.journal != 'None':
        limit = WORD_LIMITS[opts.journal]
        direction = 'OVER' if counts.total > limit else 'UNDER' if counts.total < limit else 'AT'
        percent = abs(counts.total - limit) / limit * 100
        print('Manuscript %s is currently %d words (%.0f%%) %s historical limit of %d '
              'words for journal %s' %
              (tex_file, counts.total, percent, direction, limit, opts.journal))
    return counts


def main(argv=None):
    parser = build_parser()
    opts = parser.parse_args(argv)
    validate_options(parser, opts)
    status = 0
    try:
        for tex_file in opts.tex_files:
            try:
                process(tex_file, opts)
            except (OSError, ValueError, RuntimeError) as error:
                print('%s: %s' % (tex_file, error), file=sys.stderr)
                status = 1
    except KeyboardInterrupt:
        print('Interrupted.', file=sys.stderr)
        return 130
    return status
