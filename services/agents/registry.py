"""Single place that knows every agent: builders, names, and addresses."""
from common import CORE, make_agent
from head_chat import build_head

README = {"guide": "guide.md", "checker": "checker.md", "rescuer": "rescuer.md"}


def build_core(key: str):
    """Guide, Checker and Rescuer: registered agents that run live walks (live_bureau.py adds the walk protocol)."""
    c = CORE[key]; return make_agent(c["name"], c["seed_env"], c["port"], README[key])


CORE_BUILDERS = dict(head=build_head, guide=lambda: build_core("guide"), checker=lambda: build_core("checker"), rescuer=lambda: build_core("rescuer"))


def build_all(only: set[str] | None = None) -> list:
    return [b() for k, b in CORE_BUILDERS.items() if not only or k in only]
