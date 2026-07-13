"""`deny_deploy_push_cms_dns` matcher (task instructions):

"Deny targets for deny_deploy_push_cms_dns: git push, kubectl
apply/patch/delete/create/edit, helm install/upgrade/rollback/uninstall,
terraform apply/destroy, gh pr merge, DNS/robots.txt live mutation, CMS
publish, curl|sh."

`matches_deploy_push_cms_dns` is verb-scoped (matches subcommand tokens,
never a blacklist substring search over the whole command text) precisely
so the false-positive guard case in the task instructions holds: `git
commit -m "push to prod later"` must ALLOW — `git`'s subcommand token here
is `commit`, not `push`, and the word "push" only ever appears inside a
`-m` argument value this matcher never inspects.

`curl|sh` (and its obfuscated cousins) is handled separately by
`command_normalize.has_pipe_to_interpreter` — a raw-text check, not a
segment matcher — because `|` already split it into two unrelated segments
by the time a segment matcher would see it (see that module's docstring).
"""

from __future__ import annotations

_KUBECTL_DENY_SUBS = frozenset({"apply", "patch", "delete", "create", "edit"})
_HELM_DENY_SUBS = frozenset({"install", "upgrade", "rollback", "uninstall"})
_TERRAFORM_DENY_SUBS = frozenset({"apply", "destroy"})
_CMS_BINARIES = frozenset(
    {"wp", "contentful", "sanity", "strapi", "ghost", "netlify-cms", "directus"}
)
_DNS_MUTATING_VERBS = frozenset({"create", "delete", "update", "upsert", "change"})


def _is_route53_mutation(head: str, tokens: list[str]) -> bool:
    is_route53_call = head == "aws" and len(tokens) > 1 and tokens[1] == "route53"
    return is_route53_call and "change-resource-record-sets" in tokens


def _is_gcloud_dns_mutation(head: str, tokens: list[str]) -> bool:
    is_record_sets_call = head == "gcloud" and "dns" in tokens and "record-sets" in tokens
    if not is_record_sets_call:
        return False
    is_transaction_execute = "transaction" in tokens and "execute" in tokens
    return is_transaction_execute or any(verb in tokens for verb in _DNS_MUTATING_VERBS)


def _is_az_dns_mutation(head: str, tokens: list[str]) -> bool:
    is_dns_call = head == "az" and "dns" in tokens
    return is_dns_call and any(verb in tokens for verb in _DNS_MUTATING_VERBS)


def _is_robots_txt_live_write(head: str, tokens: list[str]) -> bool:
    if "robots.txt" not in " ".join(tokens):
        return False
    is_curl_mutating_method = (
        head == "curl"
        and any(flag in tokens for flag in ("-X", "--request"))
        and any(verb in tokens for verb in ("PUT", "POST", "DELETE"))
    )
    is_object_store_upload = head in ("aws", "gsutil", "s3cmd") and any(
        verb in tokens for verb in ("cp", "sync", "put", "mv")
    )
    return is_curl_mutating_method or is_object_store_upload


def _looks_like_dns_or_robots_mutation(tokens: list[str]) -> bool:
    head = tokens[0]
    return (
        _is_route53_mutation(head, tokens)
        or _is_gcloud_dns_mutation(head, tokens)
        or _is_az_dns_mutation(head, tokens)
        or _is_robots_txt_live_write(head, tokens)
    )


def _looks_like_cms_publish(tokens: list[str]) -> bool:
    head = tokens[0]
    is_known_cms_publish_verb = head in _CMS_BINARIES and "publish" in tokens
    is_wp_post_publish = (
        head == "wp"
        and "post" in tokens
        and any(t.startswith("--post_status=publish") for t in tokens)
    )
    is_wp_json_publish_call = (
        head == "curl"
        and any("wp-json" in t for t in tokens)
        and any("publish" in t for t in tokens)
    )
    return is_known_cms_publish_verb or is_wp_post_publish or is_wp_json_publish_call


def matches_deploy_push_cms_dns(segment: str) -> str | None:
    """Return a short match description, or `None` if `segment` is not a
    deploy/push/CMS/DNS-mutating command."""
    tokens = segment.split()
    if not tokens:
        return None
    head = tokens[0]
    sub = tokens[1] if len(tokens) > 1 else ""
    sub2 = tokens[2] if len(tokens) > 2 else ""

    if head == "git" and sub == "push":
        return "git push"
    if head == "kubectl" and sub in _KUBECTL_DENY_SUBS:
        return f"kubectl {sub}"
    if head == "helm" and sub in _HELM_DENY_SUBS:
        return f"helm {sub}"
    if head == "terraform" and sub in _TERRAFORM_DENY_SUBS:
        return f"terraform {sub}"
    if head == "gh" and sub == "pr" and sub2 == "merge":
        return "gh pr merge"
    if _looks_like_dns_or_robots_mutation(tokens):
        return "DNS/robots.txt live mutation"
    if _looks_like_cms_publish(tokens):
        return "CMS publish"
    return None


__all__ = ["matches_deploy_push_cms_dns"]
