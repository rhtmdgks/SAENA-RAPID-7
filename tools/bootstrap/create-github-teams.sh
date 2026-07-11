#!/bin/sh
# Create @saena-* GitHub Teams for CODEOWNERS enforcement.
#
# Prerequisite: a GitHub Organization that owns (or will own) this repository.
# Personal user repos cannot host Teams — create/transfer to an org first:
#   https://github.com/account/organizations/new?plan=free
#
# Usage:
#   ORG=saena-labs sh tools/bootstrap/create-github-teams.sh
#   ORG=saena-labs sh tools/bootstrap/create-github-teams.sh --add-me
#
# After teams exist, rewrite CODEOWNERS entries from bare @saena-* to @ORG/saena-*
# and remove the interim @rhtmdgks owners if desired.

set -eu

ORG="${ORG:-}"
ADD_ME=0
for arg in "$@"; do
  case "$arg" in
    --add-me) ADD_ME=1 ;;
    --org=*) ORG="${arg#--org=}" ;;
  esac
done

if [ -z "$ORG" ]; then
  echo "usage: ORG=<github-org> $0 [--add-me]" >&2
  echo "error: ORG is required (personal accounts cannot host Teams)" >&2
  exit 2
fi

if ! gh api "orgs/$ORG" --jq .login >/dev/null 2>&1; then
  echo "error: org '$ORG' not found or inaccessible to this token" >&2
  echo "create a free org first: https://github.com/account/organizations/new?plan=free" >&2
  exit 1
fi

TEAMS="saena-lead saena-architecture saena-backend saena-platform saena-security saena-aeo saena-integration"

ME="$(gh api user --jq .login)"

for team in $TEAMS; do
  if gh api "orgs/$ORG/teams/$team" --jq .slug >/dev/null 2>&1; then
    echo "exists: @$ORG/$team"
  else
    echo "create: @$ORG/$team"
    gh api -X POST "orgs/$ORG/teams" \
      -f name="$team" \
      -f description="SAENA CODEOWNERS team: $team" \
      -f privacy=closed \
      --jq '"created: @\(.organization.login // "'"$ORG"'")/\(.slug)"'
  fi

  if [ "$ADD_ME" = "1" ]; then
    # maintainers can manage team membership; members count as code owners when the team has repo access
    gh api -X PUT "orgs/$ORG/teams/$team/memberships/$ME" -f role=maintainer >/dev/null
    echo "member: $ME -> @$ORG/$team (maintainer)"
  fi
done

echo
echo "Next:"
echo "  1. Transfer or grant this repo to org '$ORG' with Teams write access"
echo "  2. Rewrite CODEOWNERS to @${ORG}/saena-* and drop interim personal owners"
echo "  3. Confirm branch protection: require code owner review = on"
echo "Done."
