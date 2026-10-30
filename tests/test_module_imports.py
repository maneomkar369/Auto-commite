import importlib


MODULES = [
    "server",
    "handler",
    "github_utils",
    "autonomous_pr",
    "fork_pr",
    "push_fix",
    "llm_solver",
]


def test_modules_import_cleanly():
    for module_name in MODULES:
        importlib.import_module(module_name)
