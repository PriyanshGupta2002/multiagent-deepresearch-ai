from pathlib import Path

from langchain_core.tools import tool

SKILLS_DIR = Path(__file__).resolve().parents[1] / "skills"

SKILL_REGISTRY = {
    "academic_research": "academic_research/SKILL.md",
    "medical_research": "medical_research/SKILL.md",
    "market_research": "market_research/SKILL.md",
    "fact_checking": "fact_checking/SKILL.md",
    "report_writing": "report_writing/SKILL.md",
}


def load_base_skill() -> str:
    """Load mandatory base research methodology."""

    path = SKILLS_DIR / "base_research" / "SKILL.md"

    if not path.is_file():
        raise FileNotFoundError("Base research skill is missing")

    return path.read_text(encoding="utf-8")


@tool
def load_research_skill(skill_name: str) -> str:
    """
    Load an additional specialized research skill.

    Available skills:
    - academic_research
    - medical_research
    - market_research
    - fact_checking
    - report_writing

    Use this tool when a research task requires specialized
    domain-specific methodology.
    """
    print(f"\n[SKILL LOADER] Requested: {skill_name}")

    relative_path = SKILL_REGISTRY.get(skill_name)

    if not relative_path:
        print("[SKILL LOADER] Unknown skill")
        return "Unknown skill"

    path = SKILLS_DIR / relative_path

    if not path.is_file():
        print("[SKILL LOADER] File missing")
        return "Skill not found"

    content = path.read_text(encoding="utf-8")

    print(f"[SKILL LOADER] Successfully loaded: {skill_name}")

    return content
