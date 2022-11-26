import collections
import re
import os
import tempfile

from enum import Enum
from typing import Any, Dict, Generator, List, Tuple

from more_itertools import peekable


class Tokens(str, Enum):
    target = "target"
    command = "command"
    expression = "expression"


def tokenizer(fd: List[str]) -> Generator[Tuple[Tokens, str], None, None]:
    it = enumerate(fd)

    def glue_multiline(line: str) -> str:
        lines = []
        strip_line = line.strip()
        while strip_line[-1] == '\\':
            lines.append(strip_line.rstrip('\\').strip())
            line_num, line = next(it)
            strip_line = line.strip()
        lines.append(strip_line.rstrip('\\').strip())
        return ' '.join(lines)

    for line_num, line in it:
        strip_line = line.strip()

        # skip empty lines
        if not strip_line:
            continue

        # skip comments, don't skip docstrings
        if strip_line[0] == '#' and line[:2] != '##':
            continue
        elif line[0] == '\t':
            yield (Tokens.command, glue_multiline(line))
        elif ':' in line and '=' not in line:
            yield (Tokens.target, glue_multiline(line))
        else:
            yield (Tokens.expression, line.strip(' ;\t'))


def parse(fd: List[str]) -> List[Tuple[Tokens, Dict[str, Any]]]:
    ast = []
    it = peekable(tokenizer(fd))

    def parse_target(token: Tuple[Tokens, str]):
        line = token[1]
        target, deps, order_deps, docstring = re.match(
            r'(.+?): \s? ([^|#]+)? \s? [|]? \s? ([^##]+)? \s?  \s? ([#][#].+)?',
            line,
            re.X
        ).groups()
        body = parse_body()
        ast.append((
            token[0],
            {
                'target': target.strip(),
                'deps': [
                    sorted(deps.strip().split()) if deps else [],
                    sorted(order_deps.strip().split()) if order_deps else []
                ],
                'docs': docstring.strip().strip('#').strip() if docstring else '',
                'body': body
            })
        )

    def next_belongs_to_target() -> bool:
        token, _ = it.peek()
        return token == Tokens.command

    def parse_body() -> List[Tuple[Tokens, str]]:
        body = []
        try:
            while next_belongs_to_target():
                body.append(next(it))
        except StopIteration:
            pass
        return body

    for token in it:
        if token[0] == Tokens.target:
            parse_target(token)
        else:
            # expression
            ast.append(token)

    return ast


def get_dependencies_influences(ast: List[Tuple[Tokens, Dict[str, Any]]]):
    dependencies = {}
    influences = collections.defaultdict(set)
    order_only = set()
    indirect_influences = collections.defaultdict(set)

    for item_t, item in ast:
        if item_t != Tokens.target:
            continue
        target = item['target']
        deps, order_deps = item['deps']

        if target in ('.PHONY',):
            continue

        dependencies[target] = [deps, order_deps]

        # influences
        influences[target]
        for k in deps:
            influences[k].add(target)
        for k in order_deps:
            influences[k]
        order_only.update(order_deps)

    def recurse_indirect_influences(original_target, recurse_target):
        indirect_influences[original_target].update(influences[recurse_target])
        for t in influences[recurse_target]:
            recurse_indirect_influences(original_target, t)

    for original_target, targets in influences.items():
        for t in targets:
            recurse_indirect_influences(original_target, t)

    return dependencies, influences, order_only, indirect_influences


def check_include_instruction(filename):
    if not os.path.isfile(filename):
        return {}
    
    with open(filename, 'r') as f:
        lines = f.read().splitlines()

    # compile regex to find include instructions
    regex = re.compile('include +')
    # find rows which consist include instruction and replace multiple spaces with one
    matches = [re.sub(' +', ' ', string) for string in lines if re.match(regex, string)]
    
    # check if input make contains include instructions
    if len(matches) == 0:
        temp_make_file = open(filename, 'r')
        
    else:
        # create list of included makes
        # we use join by space and then split by space to process multiple include instructions
        makes = ' '.join([x.split('include ')[1] for x in matches]).split(' ')

        # add to initial make included makefiles
        for i in makes:
            with open(i, 'r') as fp:
                lines += fp.read().splitlines()

        # remove from final file all strings with include instruction
        make_lines_without_instrucion = [string for string in lines if not re.match(regex, string)]
        # join multiple line to single file
        final_make = '\n'.join(make_lines_without_instrucion)

        # create temporary file, which we will use 
        tmp = tempfile.NamedTemporaryFile(mode = 'w+t')

        # open temporary file and write composed make to them
        with open(tmp.name, 'w') as temp_input_file:
            temp_input_file.write(final_make)

        temp_make_file = open(tmp.name, 'r')
        
    return temp_make_file

    