from pathlib import Path
from typing import Optional, Dict, Any

try:
    import yaml
except Exception:
    yaml = None


class SkillLoader:
    """Simple SkillLoader: scans a `skills/` directory for SKILL.md files.

    Methods:
    - get_descriptions(): returns a short summary list (string) suitable for injecting into prompts
    - get_content(name): returns full SKILL.md content by skill `name` (case-insensitive)
    """

    def __init__(self, skills_dir: Optional[Path] = None):
        self.skills_dir = Path(skills_dir) if skills_dir else (Path(__file__).parent.parent / "skills")
        self.index: Dict[str, Dict[str, Any]] = {}
        self._scan_skills()

    def _scan_skills(self):
        if not self.skills_dir.exists():
            return

        for p in self.skills_dir.rglob("SKILL.md"):
            try:
                text = p.read_text(encoding="utf-8")
                name = None
                description = None

                # Try YAML frontmatter
                if text.startswith("---") and yaml:
                    parts = text.split("---", 2)
                    if len(parts) >= 3:
                        meta_text = parts[1]
                        try:
                            meta = yaml.safe_load(meta_text)
                            if isinstance(meta, dict):
                                name = meta.get("name")
                                description = meta.get("description")
                        except Exception:
                            pass

                # Fallback: use folder name as skill name
                if not name:
                    name = p.parent.name

                self.index[name] = {
                    "path": p,
                    "description": description if description is not None else "",
                    "content": text,
                }
            except Exception:
                # ignore individual file errors
                continue

    def get_descriptions(self) -> str:
        """Return a compact descriptions string (one-per-line) for prompt injection."""
        lines = []
        for name in sorted(self.index.keys()):
            desc = self.index[name].get("description") or ""
            if isinstance(desc, dict):
                # Convert block-style YAML to single-line
                desc = " ".join(str(v).strip() for v in desc.values())
            first_line = str(desc).strip().splitlines()[0] if desc else ""
            lines.append(f"- {name}: {first_line}")
        return "\n".join(lines)

    def get_content(self, name: str) -> Optional[str]:
        if not name:
            return None
        # exact match
        if name in self.index:
            return self.index[name]["content"]
        # case-insensitive exact
        lower_map = {k.lower(): k for k in self.index.keys()}
        key = lower_map.get(name.lower())
        if key:
            return self.index[key]["content"]
        # substring match
        for k in self.index.keys():
            if name.lower() in k.lower():
                return self.index[k]["content"]
        return None
