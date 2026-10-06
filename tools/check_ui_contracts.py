"""Validate stable UI, accessibility, and dashboard hierarchy contracts."""

from __future__ import annotations

from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
import re


TEMPLATES = (
    Path("templates/index.html"),
    Path("templates/login.html"),
    Path("templates/register.html"),
    Path("templates/account.html"),
    Path("templates/forgot_password.html"),
    Path("templates/reset_password.html"),
    Path("templates/auth_message.html"),
    Path("templates/gallery.html"),
)
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


class ContractParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.ids: list[str] = []
        self.parents_by_id: dict[str, str | None] = {}
        self.buttons_without_type: list[int] = []
        self.unlabelled_controls: list[str] = []
        self.dialogs_without_semantics: list[str] = []
        self.landmarks: Counter[str] = Counter()
        self.labels_for: set[str] = set()
        self.pending_controls: list[tuple[str, dict[str, str | None]]] = []

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        attrs = dict(attrs_list)
        element_id = attrs.get("id")
        if element_id:
            self.ids.append(element_id)
            self.parents_by_id[element_id] = self.stack[-1] if self.stack else None
        if tag in {"header", "nav", "main", "aside", "section"}:
            self.landmarks[tag] += 1
        if tag == "button" and not attrs.get("type"):
            self.buttons_without_type.append(self.getpos()[0])
        if tag == "label" and attrs.get("for"):
            self.labels_for.add(str(attrs["for"]))
        if tag in {"input", "select", "textarea"} and attrs.get("type") != "hidden":
            attrs["__wrapped_by_label"] = "label" in self.stack
            self.pending_controls.append((tag, attrs))
        classes = set((attrs.get("class") or "").split())
        if "gmeet-modal-backdrop" in classes or "wb-modal-overlay" in classes:
            if attrs.get("role") != "dialog" or attrs.get("aria-modal") != "true":
                self.dialogs_without_semantics.append(element_id or f"line {self.getpos()[0]}")
        if tag not in VOID_TAGS:
            self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index] == tag:
                del self.stack[index:]
                return

    def finish(self) -> None:
        for tag, attrs in self.pending_controls:
            control_id = attrs.get("id")
            labelled = attrs.get("aria-label") or attrs.get("aria-labelledby") or attrs.get("__wrapped_by_label") or (control_id and control_id in self.labels_for)
            if not labelled:
                self.unlabelled_controls.append(control_id or attrs.get("name") or f"anonymous {tag}")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    for template in TEMPLATES:
        source = template.read_text(encoding="utf-8")
        parser = ContractParser()
        parser.feed(source)
        parser.finish()
        duplicates = [element_id for element_id, count in Counter(parser.ids).items() if count > 1]
        require(not duplicates, f"{template}: duplicate IDs: {duplicates}")
        require(not parser.buttons_without_type, f"{template}: buttons without type at lines {parser.buttons_without_type}")
        require(not parser.unlabelled_controls, f"{template}: unlabelled controls: {parser.unlabelled_controls}")
        require(not parser.dialogs_without_semantics, f"{template}: dialogs missing semantics: {parser.dialogs_without_semantics}")

        html_tag = re.search(r"<html\b[^>]*lang=\"([^\"]+)\"", source, re.I)
        require(html_tag and html_tag.group(1) == "id", f"{template}: expected lang=\"id\"")

        if template.name == "index.html":
            require(parser.landmarks["header"] >= 1 and parser.landmarks["main"] == 1, "dashboard: missing primary landmarks")
            require(parser.landmarks["aside"] >= 2 and parser.landmarks["nav"] >= 2, "dashboard: hierarchy landmarks missing")
            require(parser.parents_by_id.get("recBadge") == "body", "dashboard: overlays must not be nested in bottom bar")
            for required_id in ("overviewPanel", "overviewTitle", "summaryPresence", "summaryFocus", "summaryDrowsiness", "summarySecurity", "summaryPosture"):
                require(required_id in parser.ids, f"dashboard: missing hierarchy contract #{required_id}")
            require("Google Meet" not in source, "dashboard: legacy Google Meet branding remains")
            require(
                not re.search(r'onclick="[^\"]*\$\{escapeJsString', source),
                "dashboard: dynamic client values must not be interpolated into inline onclick attributes",
            )
            for action in ("remote", "snapshot", "pin", "mute", "kick"):
                require(
                    f'data-client-action="{action}"' in source,
                    f"dashboard: missing delegated client control action {action}",
                )
            require("function handleClientControlAction" in source, "dashboard: client control dispatcher missing")

    css = Path("static/gmeet.css").read_text(encoding="utf-8")
    require(":focus-visible" in css, "CSS: visible keyboard focus contract missing")
    require("prefers-reduced-motion" in css, "CSS: reduced-motion contract missing")
    require("@media (max-width: 900px)" in css and "@media (max-width: 560px)" in css, "CSS: responsive breakpoints missing")
    print("ui_contracts_ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
