from __future__ import annotations
import json
from pathlib import Path
import httpx
from ..config import settings


async def recent_changes(service: str, limit: int = 10) -> dict:
    fixture = Path(settings.repo_root) / "fixtures" / "deployments.json"
    deployments = []
    if fixture.exists():
        deployments = [x for x in json.loads(fixture.read_text()) if x.get("service") == service][-limit:]

    commits = []
    if settings.github_repository and settings.github_token:
        headers = {"Authorization": f"Bearer {settings.github_token}", "Accept": "application/vnd.github+json"}
        async with httpx.AsyncClient(timeout=8, headers=headers) as client:
            r = await client.get(f"https://api.github.com/repos/{settings.github_repository}/commits", params={"per_page": limit})
            r.raise_for_status()
            commits = [
                {"sha": c["sha"], "message": c["commit"]["message"], "date": c["commit"]["author"]["date"]}
                for c in r.json()
            ]
    return {"service": service, "deployments": deployments, "commits": commits}


async def create_github_issue(title: str, body: str) -> dict:
    if not (settings.github_repository and settings.github_token):
        return {"simulated": True, "title": title, "body": body, "reason": "GitHub credentials not configured"}
    headers = {"Authorization": f"Bearer {settings.github_token}", "Accept": "application/vnd.github+json"}
    async with httpx.AsyncClient(timeout=8, headers=headers) as client:
        r = await client.post(
            f"https://api.github.com/repos/{settings.github_repository}/issues",
            json={"title": title, "body": body, "labels": ["opspilot", "incident"]},
        )
        r.raise_for_status()
        data = r.json()
        return {"number": data["number"], "html_url": data["html_url"]}
