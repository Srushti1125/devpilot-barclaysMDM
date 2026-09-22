import pathlib
import re

import yaml
from langchain_core.prompts import ChatPromptTemplate

PROMPT_DIR = pathlib.Path(__file__).parent / "templates"

_VERSION_RE = re.compile(r"^v(\d+)\.yaml$")


def _resolve_latest_version_file(artifact_type: str) -> pathlib.Path:
    artifact_dir = PROMPT_DIR / artifact_type
    if not artifact_dir.exists():
        raise FileNotFoundError(
            f"No prompt templates found for artifact_type='{artifact_type}' "
            f"(expected directory {artifact_dir})"
        )
    versioned = []
    for f in artifact_dir.glob("v*.yaml"):
        m = _VERSION_RE.match(f.name)
        if m:
            versioned.append((int(m.group(1)), f))
    if not versioned:
        raise FileNotFoundError(f"No versioned prompt files (v1.yaml, v2.yaml, ...) in {artifact_dir}")
    versioned.sort(key=lambda t: t[0])
    return versioned[-1][1]


def load_prompt(artifact_type: str, version: str = "latest") -> tuple[ChatPromptTemplate, str]:
    if version == "latest":
        path = _resolve_latest_version_file(artifact_type)
    else:
        path = PROMPT_DIR / artifact_type / f"{version}.yaml"
        if not path.exists():
            raise FileNotFoundError(f"Prompt version not found: {path}")

    spec = yaml.safe_load(path.read_text())
    prompt = ChatPromptTemplate.from_messages([
        ("system", spec["system"]),
        ("human", spec["human"]),
    ])
    return prompt, spec["version_id"]


def list_versions(artifact_type: str) -> list[str]:
    artifact_dir = PROMPT_DIR / artifact_type
    if not artifact_dir.exists():
        return []
    return sorted(f.stem for f in artifact_dir.glob("v*.yaml"))


def list_artifact_types() -> list[str]:
    return sorted(p.name for p in PROMPT_DIR.iterdir() if p.is_dir())
