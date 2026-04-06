from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

@dataclass(frozen=True)
class SearchConfig:
    name: str
    keyword: str | None
    location: str | None

def load_searches(yaml_path: Path) -> list[SearchConfig]:
    raw: dict[str, Any] = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))

    if "searches" not in raw or not isinstance(raw["searches"], list):
        raise ValueError("searches.yml must contain a top-level 'searches:' list")
    
    out: list[SearchConfig] = []
    for i, item in enumerate(raw["searches"]):
        if not isinstance(item, dict):
            raise ValueError(f"searches[{i}] must be a mapping")
        
        
        name = item.get("name")
        keyword = item.get("keyword")
        location = item.get("location")

        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"searches[{i}].name must be a non-empty string")
        
        if keyword is not None and not isinstance(keyword, str):
            raise ValueError(f"searches[{i}].keyword must be a string or null")
        
        if location is not None and not isinstance(location, str):
            raise ValueError(f"searches[{i}].location must be a string or null")
        
        out.append(
            SearchConfig(
                name=name.strip(),
                keyword=keyword.strip() if isinstance(keyword, str) else None,
                location=location.strip() if isinstance(location, str) else None,
            )
        )

    return out

if __name__ == "__main__":
    cfg = Path(__file__).resolve().parents[1] / "config" / "searches.yml"
    searches = load_searches(cfg)

    print(f"Loaded {len(searches)} searches:")
    for s in searches:
        print(f"- {s.name}: keyword={s.keyword!r}, location={s.location!r}")
