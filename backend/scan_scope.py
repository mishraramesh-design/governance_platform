"""Build exact-host, path-scoped URL patterns for the ZAP assessment context."""
import re


def build_zap_context_regexes(parsed_url, exclusions):
    escaped_host = re.escape(parsed_url.hostname)
    port = f":{parsed_url.port}" if parsed_url.port and parsed_url.port != 443 else ""
    root_path = parsed_url.path.rstrip("/") or "/"
    escaped_path = re.escape(root_path.rstrip("/"))
    if root_path == "/":
        scope_regex = rf"^https://{escaped_host}{port}(?:/.*)?$"
    else:
        scope_regex = rf"^https://{escaped_host}{port}{escaped_path}(?:/.*)?(?:\?.*)?$"
    excluded_regexes = []
    for excluded_path in exclusions:
        excluded_root = excluded_path.rstrip("/") or "/"
        excluded_regexes.append(
            rf"^https://{escaped_host}{port}{re.escape(excluded_root)}(?:/.*)?(?:\?.*)?$"
        )
    return scope_regex, excluded_regexes
