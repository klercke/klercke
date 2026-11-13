"""Fill TEMPLATE.md with live GitHub stats and write README.md."""

import datetime
import json
import os
import re
import urllib.request

USER = os.environ.get("GH_USER", "klercke")
TOKEN = os.environ["GITHUB_TOKEN"]
UTC = datetime.timezone.utc

PROFILE_QUERY = """
query($login: String!) {
  user(login: $login) {
    createdAt
    repositories(ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC, first: 100) {
      totalCount
      nodes { stargazerCount }
    }
    contributionsCollection {
      contributionCalendar {
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}
"""

REPO_FIELDS = "repository { nameWithOwner owner { login } }"
WINDOW_QUERY = f"""
query($login: String!, $from: DateTime!, $to: DateTime!) {{
  user(login: $login) {{
    contributionsCollection(from: $from, to: $to) {{
      contributionCalendar {{ totalContributions }}
      totalCommitContributions
      totalIssueContributions
      totalPullRequestContributions
      totalPullRequestReviewContributions
      commitContributionsByRepository(maxRepositories: 100) {{ {REPO_FIELDS} }}
      issueContributionsByRepository(maxRepositories: 100) {{ {REPO_FIELDS} }}
      pullRequestContributionsByRepository(maxRepositories: 100) {{ {REPO_FIELDS} }}
      pullRequestReviewContributionsByRepository(maxRepositories: 100) {{ {REPO_FIELDS} }}
    }}
  }}
}}
"""

BY_REPO_KEYS = (
    "commitContributionsByRepository",
    "issueContributionsByRepository",
    "pullRequestContributionsByRepository",
    "pullRequestReviewContributionsByRepository",
)


def gql(query, variables):
    body = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=body,
        headers={"Authorization": f"bearer {TOKEN}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        data = json.load(resp)
    if "errors" in data:
        raise SystemExit(f"GraphQL errors: {data['errors']}")
    return data["data"]["user"]


def window(start, end):
    """Totals and the set of other people's repos contributed to between start and end."""
    cc = gql(WINDOW_QUERY, {"login": USER, "from": start.isoformat(), "to": end.isoformat()})
    cc = cc["contributionsCollection"]
    repos = {
        entry["repository"]["nameWithOwner"]
        for key in BY_REPO_KEYS
        for entry in cc[key]
        if entry["repository"]["owner"]["login"].lower() != USER.lower()
    }
    return {
        "CONTRIBUTIONS": cc["contributionCalendar"]["totalContributions"],
        "COMMITS": cc["totalCommitContributions"],
        "ISSUES": cc["totalIssueContributions"],
        "PULL_REQUESTS": cc["totalPullRequestContributions"],
        "REVIEWS": cc["totalPullRequestReviewContributions"],
    }, repos


def all_time(created, now):
    """Sum every year since signup. GitHub caps each query at one year.

    Windows are whole UTC days that don't overlap, so no day is counted twice.
    """
    totals, repos = {}, set()
    start = datetime.datetime.combine(created.date(), datetime.time.min, UTC)
    while start <= now:
        end = min(start + datetime.timedelta(days=365, seconds=-1), now)
        counts, window_repos = window(start, end)
        for key, value in counts.items():
            totals[key] = totals.get(key, 0) + value
        repos |= window_repos
        start = end + datetime.timedelta(seconds=1)
    return totals, repos


def streak(weeks):
    days = sorted((d for w in weeks for d in w["contributionDays"]), key=lambda d: d["date"])
    if days and days[-1]["contributionCount"] == 0:
        days = days[:-1]  # today isn't over yet, so don't break the streak on it
    count = 0
    for day in reversed(days):
        if day["contributionCount"] == 0:
            break
        count += 1
    return count


def stats():
    now = datetime.datetime.now(UTC)
    user = gql(PROFILE_QUERY, {"login": USER})
    created = datetime.datetime.fromisoformat(user["createdAt"].replace("Z", "+00:00"))

    last_year, last_year_repos = window(now - datetime.timedelta(days=365), now)
    lifetime, lifetime_repos = all_time(created, now)

    values = {
        "ACCOUNT_AGE": (now - created).days // 365,
        "REPOSITORIES": user["repositories"]["totalCount"],
        "STARS": sum(r["stargazerCount"] for r in user["repositories"]["nodes"]),
        "STREAK": streak(user["contributionsCollection"]["contributionCalendar"]["weeks"]),
        "UPDATED": now.date().isoformat(),
        "LY_CONTRIBUTED_TO": len(last_year_repos),
        "AT_CONTRIBUTED_TO": len(lifetime_repos),
    }
    values.update({f"LY_{k}": v for k, v in last_year.items()})
    values.update({f"AT_{k}": v for k, v in lifetime.items()})
    return values


REPO_PLACEHOLDER = re.compile(r"\{\{ REPO:([\w.-]+)/([\w.-]+) \}\}")


def repo_links(template):
    """Expand {{ REPO:owner/name }} into a link plus the repo's own GitHub description."""
    found = sorted(set(REPO_PLACEHOLDER.findall(template)))
    if not found:
        return {}
    fields = "\n".join(
        f'r{i}: repository(owner: "{owner}", name: "{name}") {{ name url description }}'
        for i, (owner, name) in enumerate(found)
    )
    body = json.dumps({"query": f"query {{ {fields} }}"}).encode()
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=body,
        headers={"Authorization": f"bearer {TOKEN}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        data = json.load(resp).get("data") or {}

    links = {}
    for i, (owner, name) in enumerate(found):
        key = f"REPO:{owner}/{name}"
        repo = data.get(f"r{i}")
        if repo is None:
            # Private, renamed, or missing: show the name without a dead link.
            print(f"warning: {owner}/{name} not found, rendering without a link")
            links[key] = name
            continue
        description = (repo["description"] or "").strip()
        # Drop a leading "name: " so "[d0cuments](...): d0cuments: my blog" doesn't repeat itself.
        prefix = f"{repo['name']}:".lower()
        if description.lower().startswith(prefix):
            description = description[len(prefix):].strip()
        link = f"[{repo['name']}]({repo['url']})"
        links[key] = f"{link}: {description}" if description else link
    return links


def render(template, values):
    for key, value in values.items():
        template = template.replace("{{ " + key + " }}", str(value))
    return template


if __name__ == "__main__":
    with open("TEMPLATE.md") as f:
        template = f.read()
    values = stats()
    values.update(repo_links(template))
    out = render(template, values)
    with open("README.md", "w") as f:
        f.write(out)
    print(json.dumps(values, indent=2))
