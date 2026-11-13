"""Fill TEMPLATE.md with live GitHub stats and write README.md."""

import datetime
import json
import os
import urllib.request

USER = os.environ.get("GH_USER", "klercke")
TOKEN = os.environ["GITHUB_TOKEN"]

QUERY = """
query($login: String!) {
  user(login: $login) {
    createdAt
    repositories(ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC, first: 100) {
      totalCount
      nodes { stargazerCount }
    }
    repositoriesContributedTo(
      contributionTypes: [COMMIT, PULL_REQUEST, ISSUE, PULL_REQUEST_REVIEW]
      includeUserRepositories: false
    ) { totalCount }
    pullRequests { totalCount }
    issues { totalCount }
    contributionsCollection {
      totalCommitContributions
      restrictedContributionsCount
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}
"""


def fetch():
    body = json.dumps({"query": QUERY, "variables": {"login": USER}}).encode()
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


def streak(weeks):
    days = [d for w in weeks for d in w["contributionDays"]]
    days.sort(key=lambda d: d["date"])
    if days and days[-1]["contributionCount"] == 0:
        days = days[:-1]  # today isn't over yet, so don't break the streak on it
    count = 0
    for day in reversed(days):
        if day["contributionCount"] == 0:
            break
        count += 1
    return count


def stats(user):
    created = datetime.datetime.fromisoformat(user["createdAt"].replace("Z", "+00:00"))
    years = (datetime.datetime.now(datetime.timezone.utc) - created).days // 365
    cc = user["contributionsCollection"]
    return {
        "ACCOUNT_AGE": years,
        "CONTRIBUTIONS": cc["contributionCalendar"]["totalContributions"],
        "COMMITS": cc["totalCommitContributions"] + cc["restrictedContributionsCount"],
        "PULL_REQUESTS": user["pullRequests"]["totalCount"],
        "ISSUES": user["issues"]["totalCount"],
        "REPOSITORIES": user["repositories"]["totalCount"],
        "STARS": sum(r["stargazerCount"] for r in user["repositories"]["nodes"]),
        "CONTRIBUTED_TO": user["repositoriesContributedTo"]["totalCount"],
        "STREAK": streak(cc["contributionCalendar"]["weeks"]),
        "UPDATED": datetime.date.today().isoformat(),
    }


def render(template, values):
    for key, value in values.items():
        template = template.replace("{{ " + key + " }}", str(value))
    return template


if __name__ == "__main__":
    values = stats(fetch())
    with open("TEMPLATE.md") as f:
        out = render(f.read(), values)
    with open("README.md", "w") as f:
        f.write(out)
    print(json.dumps(values, indent=2))
