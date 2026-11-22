"""Text, equation, and table counts, independent of command-line reporting."""

import os
from pathlib import Path
import shlex
import sys

from . import tex, tools


def count_chars_abstract(document):
    abstracts = document.find_environments(('abstract',))
    if not abstracts:
        raise ValueError(r'Could not find \begin{abstract}')
    if len(abstracts) > 1:
        raise ValueError('Found multiple abstract environments')
    abstract = abstracts[0]
    # This is a source-character count, as in the original tool, not a count of
    # rendered glyphs. Exclude delimiters, comments, and boundary whitespace.
    return len(tex.remove_comments(document.source[abstract.body_start:abstract.body_end]).strip())


def wordcount_source(document, ignored_envs):
    """Filter indexed source ranges while retaining every original offset."""
    # Retain captions but exclude the table cells already charged geometrically.
    spans = [(span.start, span.end) for span in
             document.find_environments((*ignored_envs, *tex.TABULAR_ENVS), outermost=True)]
    source = tex.blank_spans(document.source, spans)
    spans = []
    for match in tex.command_matches(r'\\(?:maketitle\b|bibliographystyle\s*\{[^{}]*\})', source):
        spans.append(match.span())
    for command in tex.includegraphics_commands(source):
        spans.append((command.start, command.end))
    source = tex.blank_spans(source, spans)
    # REVTeX also permits a command-form acknowledgments section.
    acknowledgment = next(tex.command_matches(r'\\acknowledg(?:e)?ments?\b', source), None)
    if acknowledgment:
        documents = document.find_environments(('document',))
        if not documents:
            raise ValueError(r'Could not find \begin{document}')
        source = tex.blank_spans(source, [(acknowledgment.start(), documents[0].body_end)])
    return source


def bibliography_environment(directory):
    env = os.environ.copy()
    # A trailing empty entry preserves BibTeX's standard search directories.
    for variable in ('BIBINPUTS', 'BSTINPUTS'):
        env[variable] = str(directory) + os.pathsep + env.get(variable, '')
    return env


def count_main_text_words_wordcount(document, opts, directory):
    source = tex.add_documentclass_option(wordcount_source(document, opts.env), 'nofootinbib')
    with tools.temporary_workspace(opts.keep_tmp_files) as temporary:
        manuscript = temporary / 'manuscript.tex'
        wordcount = temporary / 'wordcount.tex'
        manuscript.write_text(source, encoding='utf-8')
        wordcount.write_bytes(Path(__file__).with_name('wordcount.tex').read_bytes())
        latex = (shlex.split(opts.latex) + shlex.split(opts.latexopts) +
                 ['-synctex=1', '-output-directory=' + str(temporary)])

        def run(command, log_path=None, input_text=None, cwd=directory, env=None):
            completed = tools.run_command(
                command, cwd=cwd, env=env, input_text=input_text,
                timeout=opts.timeout, log_path=log_path, check=False)
            if completed.returncode:
                message = tools.command_failure(command, completed, log_path)
                if not opts.ignoreerrors:
                    raise RuntimeError('LaTeX error encountered\n' + message)
                print('Warning: continuing after %s' % message, file=sys.stderr)

        run(latex + [str(manuscript)], temporary / 'manuscript.log')
        aux_path = temporary / 'manuscript.aux'
        aux = aux_path.read_text(errors='replace') if aux_path.is_file() else ''
        # BibTeX exits with an error for documents without a bibliography.
        if all(command in aux for command in (r'\citation', r'\bibdata', r'\bibstyle')):
            run(['bibtex', 'manuscript'], cwd=temporary,
                env=bibliography_environment(directory))
        for _ in range(2):
            run(latex + [str(manuscript)], temporary / 'manuscript.log')
        log_path = temporary / 'wordcount.log'
        run(latex + [str(wordcount)], log_path, str(manuscript) + '\n')
        if not log_path.is_file():
            raise RuntimeError('LaTeX did not produce a word-count log: %s' % log_path)
        with log_path.open('rb') as log:
            return sum(b'3.08633' in line or b'3.08635' in line for line in log)


def count_main_text_words_detex(document, opts, directory):
    # Apply the same filters to both backends; locate the body in TeX source,
    # rather than guessing where a rendered line occurs in detex's output.
    title = next(tex.command_matches(r'\\maketitle\b', document.source), None)
    documents = document.find_environments(('document',))
    if not documents:
        raise ValueError(r'Could not find \begin{document}')
    source = wordcount_source(document, opts.env)
    body_environment = documents[0]
    if title and body_environment.body_start <= title.start() < body_environment.body_end:
        source = tex.blank_spans(source, [(body_environment.body_start, title.end())])
    body = source[body_environment.body_start:body_environment.body_end]
    with tools.temporary_workspace(opts.keep_tmp_files) as temporary:
        manuscript = temporary / 'manuscript.tex'
        manuscript.write_text(body, encoding='utf-8')
        completed = tools.run_command(['detex', '-l', str(manuscript)],
                                      cwd=directory, timeout=opts.timeout)
    text = tools.decode_output(completed.stdout)
    text = '\n'.join(line for line in text.splitlines() if '<Picture' not in line)
    return len(text.replace('-', ' ').split())


def logical_rows(document, start=0, end=None):
    """Add row heights, using the tallest nested environment in each row."""
    total = 0
    for row in tex.iter_rows(document, start, end):
        height = 1
        for environment in row.environments:
            body_start = (tex.tabular_body_start(document, environment)
                          if environment.name == 'array' else environment.body_start)
            height = max(height, logical_rows(document, body_start, environment.body_end))
        total += height
    return total


def count_equations_words(document):
    equations = document.find_environments(tex.DISPLAY_MATH_ENVS, outermost=True)
    wide = document.find_environments(('widetext',))
    counts = []
    for equation in equations:
        two_column = any(span.body_start <= equation.start < span.body_end for span in wide)
        rows = max(1, logical_rows(document, equation.body_start, equation.body_end))
        counts.append(rows * (32 if two_column else 16))
    print('Equations: %r' % counts)
    return sum(counts)


def count_tables_words(document):
    tables = document.find_environments(('table',))
    counts = []
    for table in tables:
        tabulars = document.find_environments(tex.TABULAR_ENVS, within=table, outermost=True)
        rows = sum(logical_rows(document, tex.tabular_body_start(document, tabular), tabular.body_end)
                   for tabular in tabulars)
        if not rows:
            raise ValueError('Table near line %d has no supported tabular rows' %
                             (document.source.count('\n', 0, table.start) + 1))
        counts.append(int(13 * rows + 26 if table.name == 'table*' else 6.5 * rows + 13))
    print('Tables: %r' % counts)
    return sum(counts)
