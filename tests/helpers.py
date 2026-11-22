from aps_length.cli import build_parser, validate_options


def options(*arguments):
    parser = build_parser()
    opts = parser.parse_args(['paper.tex', *arguments])
    validate_options(parser, opts)
    return opts


def document(body='', abstract='An abstract.'):
    return (r'\documentclass{revtex4-2}' + '\n' +
            r'\begin{document}' + '\n' +
            r'\title{A title}\author{A. Author}' + '\n' +
            r'\begin{abstract}' + abstract + r'\end{abstract}' + '\n' +
            r'\maketitle ' + body + '\n' + r'\end{document}' + '\n')
