import inspect
from contextlib import contextmanager
import argparse
from typing import List, Dict, Tuple
import docstring_parser
import textwrap
import yaml
import sys
import os
from pathlib import Path
import ast

PARSE_FUNCS = {}
ARGS = {}
USED_ARGS = {}
PATTERN = None
DEBUG = False
HELP_WIDTH = 60

@contextmanager
def scope(parsed_args, pattern=''):
    """
    Context manager to put parsed arguments into 
    a state.
    """
    parsed_args = parsed_args.copy()
    remove_keys = []
    matched = {}

    global ARGS
    global PATTERN

    old_args = ARGS
    old_pattern = PATTERN

    for key in parsed_args:
        if '/' in key:
            if key.split('/')[0] == pattern:
                matched[key.split('/')[-1]] = parsed_args[key]
            remove_keys.append(key)
    
    parsed_args.update(matched)
    for key in remove_keys:
        parsed_args.pop(key)
    ARGS = parsed_args
    PATTERN = pattern
    yield

    ARGS = old_args
    PATTERN = old_pattern

def bind_to_parser(*patterns, no_global=False):
    """
    Wrap the function so it looks in ARGS (managed 
    by the scope context manager) for keyword 
    arguments.
    """

    def decorator(func):
        PARSE_FUNCS[func.__name__] = (func, patterns, no_global)
        def cmd_func(*args, **kwargs):
            prefix = func.__name__
            sig = inspect.signature(func)
            cmd_kwargs = {}

            for key, val in sig.parameters.items():
                arg_type = val.annotation
                arg_val = val.default
                if arg_val is not inspect.Parameter.empty:
                    arg_name = f'{prefix}.{key}'
                    if arg_name in ARGS and key not in kwargs:
                        cmd_kwargs[key] = ARGS[arg_name]
                        use_key = arg_name
                        if PATTERN:
                            use_key = f'{PATTERN}/{use_key}'
                        USED_ARGS[use_key] = ARGS[arg_name]
            
            kwargs.update(cmd_kwargs)
            if 'args.debug' not in ARGS: ARGS['args.debug'] = False
            if ARGS['args.debug'] or DEBUG:
                _prefix = f"{PATTERN}/{prefix}" if PATTERN else prefix
                print(f"{_prefix} <- {parse_dict_to_str(kwargs)}")

            return func(*args, **kwargs)
        return cmd_func
    
    return decorator

def parse_dict_to_str(x):
    return ', '.join([f'{k}={v}' for k, v in x.items()])

def get_used_args():
    """
    Gets the args that have been used so far
    by the script (e.g. their function they target
    was actually called).
    """
    return USED_ARGS

def dump_args(args, output_path):
    """
    Dumps the provided arguments to a
    file.
    """
    path = Path(output_path)
    os.makedirs(path.parent, exist_ok=True)
    with open(path, 'w') as f:
        yaml.Dumper.ignore_aliases = lambda *args : True
        x = yaml.dump(args, Dumper=yaml.Dumper)
        prev_line = None
        output = []
        for line in x.split('\n'):
            cur_line = line.split('.')[0].strip()
            if not cur_line.startswith('-'):
                if cur_line != prev_line and prev_line:
                    line = f'\n{line}'
                prev_line = line.split('.')[0].strip()
            output.append(line)
        f.write('\n'.join(output))

def load_args(input_path):
    """
    Loads arguments from a given input path. If $include key is in
    the args, you can include other y
    """
    with open(input_path, 'r') as f:
        data = yaml.load(f, Loader=yaml.Loader)
    
    if '$include' in data:
        include_files = data.pop('$include')
        include_args = {}
        for include_file in include_files:
            with open(include_file, 'r') as f:
                _include_args = yaml.load(f, Loader=yaml.Loader)
            include_args.update(_include_args)
        include_args.update(data)
        data = include_args

    if '$vars' in data:
        _vars = data.pop('$vars')
        for key, val in data.items():
            # Check if string starts with $.
            if isinstance(val, str) and val.startswith('$'):
                lookup = val[1:]
                if lookup in _vars:
                    data[key] = _vars[lookup]

    if 'args.debug' not in data:
        data['args.debug'] = DEBUG
    return data

class str_to_list():
    def __init__(self, _type):
        self._type = _type
    def __call__(self, values):
        _values = values.split(' ')
        _values = [self._type(v) for v in _values]
        return _values

class str_to_tuple():
    def __init__(self, _type_list):
        self._type_list = _type_list
    def __call__(self, values):
        _values = values.split(' ')
        _values = [self._type_list[i](v) for i, v in enumerate(_values)]
        return tuple(_values)

class str_to_dict():
    def __init__(self):
        pass

    def _guess_type(self, s):
        try:
            value = ast.literal_eval(s)
        except ValueError:
            return s
        else:
            return value

    def __call__(self, values):
        values = values.split(' ')
        _values = {}

        for elem in values:
            key, val = elem.split('=', 1)
            key = self._guess_type(key)
            val = self._guess_type(val)
            _values[key] = val

        return _values

def parse_args():
    """
    Goes through all detected functions that are
    bound and adds them to the argument parser,
    along with their scopes. Then parses the
    command line and returns a dictionary.
    """
    p = argparse.ArgumentParser(
        formatter_class=argparse.RawTextHelpFormatter
    )

    p.add_argument('--args.save', type=str, required=False, 
        help="Path to save all arguments used to run script to.")
    p.add_argument('--args.load', type=str, required=False,
        help="Path to load arguments from, stored as a .yml file.")
    p.add_argument('--args.debug', type=int, required=False, default=0, 
        help="Print arguments as they are passed to each function.")

    # Add kwargs from function to parser
    for func_name in PARSE_FUNCS:
        func, patterns, no_global = PARSE_FUNCS[func_name]
        sig = inspect.signature(func)
        prefix = func.__name__

        docstring = docstring_parser.parse(func.__doc__)
        parameter_help = docstring.params
        parameter_help = {
            x.arg_name: x.description for x in parameter_help
        }

        f = p.add_argument_group(
            title=f"Generated arguments for function {prefix}",
        )

        for key, val in sig.parameters.items():
            arg_type = val.annotation
            arg_val = val.default

            if arg_val is not inspect.Parameter.empty:
                arg_names = []
                arg_help = {}
                help_text = ''
                if key in parameter_help:
                    help_text = textwrap.fill(parameter_help[key], width=HELP_WIDTH)
                if not no_global:
                    arg_names.append(f'--{prefix}.{key}')
                    arg_help[arg_names[-1]] = help_text
                for pattern in patterns:
                    arg_names.append(f'--{pattern}/{prefix}.{key}')
                    arg_help[arg_names[-1]] = argparse.SUPPRESS
                for arg_name in arg_names:
                    inner_types = [str, int, float, bool]
                    list_types = [List[x] for x in inner_types]

                    if arg_type is bool:
                        f.add_argument(arg_name, action='store_true', 
                            help=arg_help[arg_name])
                    elif arg_type in list_types:
                        _type = inner_types[list_types.index(arg_type)]
                        f.add_argument(arg_name, type=str_to_list(_type), 
                            default=arg_val, help=arg_help[arg_name])
                    elif arg_type is Dict:
                        f.add_argument(arg_name, type=str_to_dict(), 
                            default=arg_val, help=arg_help[arg_name])
                    elif hasattr(arg_type, '__origin__'):
                        if arg_type.__origin__ is tuple:
                            _type_list = arg_type.__args__
                            f.add_argument(arg_name, type=str_to_tuple(_type_list), 
                                default=arg_val, help=arg_help[arg_name])
                    else:
                        f.add_argument(arg_name, type=arg_type, 
                            default=arg_val, help=arg_help[arg_name])
            
        desc = docstring.short_description
        if desc is None: desc = ''

        if patterns:
            desc += (
                f" Additional scope patterns: {', '.join(list(patterns))}. "
                "Use these by prefacing any of the args below with one "
                "of these patterns. For example: "
                f"--{patterns[0]}/{prefix}.{key} VALUE."
            )

        desc = textwrap.fill(desc, width=HELP_WIDTH)
        f.description = desc
    
    used_args = [x.replace('--', '').split('=')[0] for x in sys.argv if x.startswith('--')]
    used_args.extend(['args.save', 'args.load'])

    args = vars(p.parse_args())
    load_args_path = args.pop('args.load')
    save_args_path = args.pop('args.save')
    debug_args = args.pop('args.debug')
    
    pattern_keys = [key for key in args if '/' in key]
    top_level_args = [key for key in args if '/' not in key]

    for key in pattern_keys:
        # If the top-level arguments were altered but the ones
        # in patterns were not, change the scoped ones to
        # match the top-level (inherit arguments from top-level).
        pattern, arg_name = key.split('/')
        if key not in used_args:
            args[key] = args[arg_name]
    
    if load_args_path:
        loaded_args = load_args(load_args_path)
        # Overwrite defaults with things in loaded arguments.
        # except for things that came from the command line.
        for key in loaded_args:
            if key not in used_args:
                args[key] = loaded_args[key]
        for key in pattern_keys:
            pattern, arg_name = key.split('/')
            if key not in loaded_args and key not in used_args:
                if arg_name in loaded_args:
                    args[key] = args[arg_name]
                
    for key in top_level_args:
        if key in used_args:
            for pattern_key in pattern_keys:
                pattern, arg_name = pattern_key.split('/')
                if key == arg_name and pattern_key not in used_args:
                    args[pattern_key] = args[key]

    if save_args_path:
        dump_args(args, save_args_path)

    # Put them back in case the script wants to use them
    args['args.load'] = load_args_path
    args['args.save'] = save_args_path
    args['args.debug'] = debug_args
    
    return args
