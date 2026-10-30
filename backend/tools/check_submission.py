"""Read-only secret checks for staged files, or explicitly selected working files."""

from __future__ import annotations

import argparse
import ast
import io
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

SECRET_KEY = re.compile(
    r"(?:password|passwd|(?:^|_)pwd|secret|api[_-]?key|token)",
    re.IGNORECASE,
)
ASSIGNMENT = re.compile(
    r"(?<![\w])(?:[\"'])?(?P<key>[A-Za-z_][\w-]*)(?:[\"'])?\s*[:=]\s*"
    r"(?P<quote>[\"'])(?P<value>[^\"'\r\n]+)(?P=quote)"
)
DSN = re.compile(
    r"\b(?:mysql(?:\+pymysql)?|postgres(?:ql)?|redis|mongodb(?:\+srv)?|https?)://"
    r"[^\s/:<>\"']+:(?P<value>[^\s/@<>\"']+)@",
    re.IGNORECASE,
)
PRIVATE_KEY = re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----")
PROVIDER_TOKEN = re.compile(
    r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,}"
    r"|sk-[A-Za-z0-9_-]{20,}|AKIA[A-Z0-9]{16})\b"
)
ENV_LINE = re.compile(r"^\s*(?:export\s+)?(?P<key>[A-Z][A-Z0-9_]*)\s*=\s*(?P<value>.*)$")
ENV_DEFAULT = re.compile(r"\$\{(?P<key>[A-Za-z_][A-Za-z0-9_]*):[-=](?P<value>[^}]+)\}")
INLINE_PASSWORD = re.compile(
    r"(?:密码|口令)\s*[:：=]\s*[`\"']?(?P<value>[A-Za-z0-9][A-Za-z0-9@+%_!./:-]{7,})"
)
SQL_IDENTITIES = re.compile(
    r"\bINSERT\s+(?:IGNORE\s+)?INTO\s+[`\"]?platform_users[`\"]?"
    r"\s*\((?P<columns>[^)]+)\)\s*VALUES\s*(?P<rows>[^;]+)",
    re.IGNORECASE,
)
MAX_BYTES = 100 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 512


@dataclass(frozen=True, order=True)
class Finding:
    path: str
    line: int
    kind: str


def placeholder(value: str) -> bool:
    """Accept explicit templates, never a usable default merely called a demo."""
    value = unquote(value.strip().strip("`\"'"))
    if not value:
        return True
    if "编码" in value and any(word in value for word in ("密码", "口令")):
        return True
    if re.fullmatch(r"(?:<[^>]+>|\[[^\]]+\]|\$\{[^}]+\}|\$[A-Za-z_][\w]*)", value):
        return True
    normalized = value.lower().replace("-", "_").replace(" ", "_")
    if normalized in {
        "password",
        "password_here",
        "secret",
        "token",
        "changeme",
        "change_me",
        "replace_me",
        "redacted",
        "encoded",
        "encoded_password",
        "url_encoded_password",
        "none",
        "null",
    }:
        return True
    return bool(
        re.fullmatch(r"(?:your|replace_with|enter|insert)_[a-z_]+", normalized)
        or re.fullmatch(r"(?:url_?encoded|encoded)(?:_[a-z_]+)?", normalized)
        or (
            re.fullmatch(r"[A-Z][A-Z_]+", value)
            and re.search(r"ENCODED|REPLACE|YOUR|PLACEHOLDER", value)
            and re.search(r"PASSWORD|SECRET|TOKEN", value)
        )
    )


def credential_literal(value: str, path: str) -> bool:
    if placeholder(value) or len(value) < 4:
        return False
    # Invalid-login fixtures are not credentials. Known-local-secret comparison still runs.
    if "/tests/" in "/" + path.replace("\\", "/"):
        if re.match(r"^(?:wrong|invalid|incorrect|not[-_]the[-_]password)(?:[-_]|$)", value, re.I):
            return False
    return True


def git(root: Path, *arguments: str) -> bytes:
    result = subprocess.run(["git", "-C", str(root), *arguments], capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError("git_command_failed")
    return result.stdout


def local_secrets(root: Path) -> set[str]:
    """Inspect only ignored local env files. Never return their names or values to output."""
    found: set[str] = set()
    for directory in (root, root / "backend", root / "frontend"):
        if not directory.is_dir():
            continue
        for path in directory.glob(".env*"):
            if not path.is_file() or path.name.endswith(".example"):
                continue
            relative = path.relative_to(root)
            ignored = subprocess.run(
                ["git", "-C", str(root), "check-ignore", "--quiet", "--", str(relative)],
                capture_output=True,
                check=False,
            )
            if ignored.returncode != 0:
                continue
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except UnicodeError as exc:
                raise RuntimeError("env_read_failed") from exc
            for line in lines:
                match = ENV_LINE.match(line)
                if not match:
                    continue
                key = match["key"]
                value = match["value"].split(" #", 1)[0].strip().strip("\"'")
                if "://" in value:
                    try:
                        parsed = urlsplit(value)
                        if parsed.password and not placeholder(parsed.password):
                            password = unquote(parsed.password)
                            if len(password) >= 6:
                                found.update({password, quote(password, safe="")})
                                found.add(value)
                    except ValueError:
                        pass
                if SECRET_KEY.search(key) and len(value) >= 8 and not placeholder(value):
                    found.update({value, quote(value, safe="")})
    return found


def python_defaults(path: str, text: str) -> set[Finding]:
    findings: set[Finding] = set()
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return findings
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or len(node.args) < 2:
            continue
        function = node.func
        if not isinstance(function, ast.Attribute) or function.attr not in {"get", "getenv"}:
            continue
        key, default = node.args[:2]
        if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
            continue
        if not SECRET_KEY.search(key.value):
            continue
        if isinstance(default, ast.Constant) and isinstance(default.value, str):
            if credential_literal(default.value, path):
                findings.add(Finding(path, default.lineno, "embedded_credential_default"))
    return findings


def check_text(path: str, text: str, known: set[str]) -> set[Finding]:
    findings: set[Finding] = set()
    original = text
    # PDF fonts and document editors can turn delimiter quotes into typographic quotes.
    # This substitution preserves offsets and never changes printed output values.
    text = text.translate(str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "\u00a0": " "}))

    def record(offset: int, kind: str) -> None:
        findings.add(Finding(path, text.count("\n", 0, offset) + 1, kind))

    for kind, pattern in (("private_key", PRIVATE_KEY), ("provider_token", PROVIDER_TOKEN)):
        for match in pattern.finditer(text):
            record(match.start(), kind)
    for match in DSN.finditer(text):
        if not placeholder(match["value"]):
            record(match.start(), "credential_in_url")
    for match in ASSIGNMENT.finditer(text):
        if SECRET_KEY.search(match["key"]) and credential_literal(match["value"], path):
            # Hashes and field names are not plaintext passwords; SQL credential dumps
            # are identified separately without flagging CREATE TABLE declarations.
            if not re.search(r"(?:hash|salt|_id)$", match["key"], re.I):
                record(match.start(), "embedded_credential")
    for match in ENV_DEFAULT.finditer(text):
        if SECRET_KEY.search(match["key"]) and credential_literal(match["value"], path):
            record(match.start(), "embedded_credential_default")
    for match in INLINE_PASSWORD.finditer(text):
        if credential_literal(match["value"], path):
            record(match.start(), "document_credential")
    offset = 0
    for line in text.splitlines(keepends=True):
        match = ENV_LINE.match(line)
        if match and SECRET_KEY.search(match["key"]):
            value = match["value"].split(" #", 1)[0].strip().strip("\"'")
            is_env_value = not re.search(r"[\s();{}]|\b(?:os|process)\.", value)
            if credential_literal(value, path) and is_env_value:
                record(offset, "embedded_credential")
        if re.search(r"\b(?:PASSWORD|password|passwd|secret|api_key)\b", line):
            fallback = re.search(r"(?:\|\||\?\?)\s*([\"'])([^\"'\n]+)\1", line)
            if fallback and credential_literal(fallback[2], path):
                record(offset, "embedded_credential_default")
        offset += len(line)
    if path.endswith(".py"):
        findings.update(python_defaults(path, text))
    if path.lower().endswith(".sql"):
        for match in SQL_IDENTITIES.finditer(text):
            if re.search(r"password_hash|salt", match["columns"], re.I):
                if re.search(r"['\"][0-9a-f]{32,}['\"]", match["rows"], re.I):
                    record(match.start(), "sql_account_credential_dump")
    for value in known:
        start = 0
        while (index := original.find(value, start)) >= 0:
            record(index, "known_local_secret")
            start = index + len(value)
    return findings


def document_text(path: str, data: bytes, depth: int = 0) -> tuple[list[tuple[str, str]], str]:
    suffix = Path(path).suffix.lower()
    if len(data) > MAX_BYTES:
        raise ValueError("file_size_limit")
    if suffix in {".docx", ".zip"}:
        if depth > 2:
            raise ValueError("archive_depth_limit")
        texts: list[tuple[str, str]] = []
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = archive.infolist()
            if len(members) > MAX_ARCHIVE_MEMBERS:
                raise ValueError("archive_member_limit")
            if sum(member.file_size for member in members) > MAX_BYTES:
                raise ValueError("archive_size_limit")
            for member in members:
                if member.is_dir():
                    continue
                member_path = path + "!" + member.filename
                raw = archive.read(member)
                if member.filename.endswith((".xml", ".rels")):
                    root = ET.fromstring(raw)
                    # Include XML attributes as well as text (hyperlink targets can leak).
                    paragraphs = list(
                        root.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p")
                    )
                    lines = ["".join(element.itertext()) for element in paragraphs or [root]]
                    lines.extend(
                        value
                        for element in root.iter()
                        for value in element.attrib.values()
                        if value.strip()
                    )
                    texts.append((member_path, "\n".join(lines)))
                elif suffix == ".zip":
                    nested, _ = document_text(member_path, raw, depth + 1)
                    texts.extend(nested)
        return texts, suffix[1:]
    if suffix == ".pdf":
        try:
            result = subprocess.run(
                ["pdftotext", "-", "-"],
                input=data,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=30,
                check=False,
            )
        except FileNotFoundError as exc:
            raise ValueError("pdftotext_required") from exc
        if result.returncode:
            raise ValueError("pdf_text_extraction_failed")
        return [(path, result.stdout.decode("utf-8"))], "pdf"
    if b"\0" in data:
        return [], "binary_skipped"
    try:
        return [(path, data.decode("utf-8"))], "text"
    except UnicodeDecodeError:
        return [], "binary_skipped"


def scan(root: Path, working_tree: bool = False) -> dict:
    arguments = (
        ("ls-files", "--cached", "--others", "--exclude-standard", "-z")
        if working_tree
        else ("diff", "--cached", "--name-only", "--diff-filter=ACMRT", "-z")
    )
    paths = sorted(set(path for path in git(root, *arguments).decode().split("\0") if path))
    known = local_secrets(root)
    findings: set[Finding] = set()
    errors: list[dict[str, str]] = []
    counts: Counter[str] = Counter()
    for path in paths:
        try:
            if working_tree:
                source = root / path
                if not source.exists():
                    continue
                if not source.resolve().is_relative_to(root.resolve()):
                    raise ValueError("external_symlink_skipped")
                data = source.read_bytes()
            else:
                data = git(root, "cat-file", "blob", ":" + path)
            texts, kind = document_text(path, data)
            counts[kind] += 1
            for name, text in texts:
                findings.update(check_text(name, text, known))
        except (OSError, ValueError, ET.ParseError, zipfile.BadZipFile, RuntimeError) as exc:
            # Do not surface exception text: third-party errors may contain payload data.
            reason = str(exc) if type(exc) in {ValueError, RuntimeError} else type(exc).__name__
            if not re.fullmatch(r"[a-z_]+", reason):
                reason = type(exc).__name__
            errors.append({"path": path, "kind": reason})
        except subprocess.TimeoutExpired:
            errors.append({"path": path, "kind": "extraction_timeout"})
    return {
        "scope": "working_tree" if working_tree else "staged",
        "files": sum(counts.values()),
        "formats": dict(counts),
        "finding_count": len(findings),
        "findings": [asdict(item) for item in sorted(findings)],
        "error_count": len(errors),
        "errors": errors,
    }


def main() -> int:
    if sys.version_info[:2] != (3, 12):
        raise SystemExit("Python 3.12 is required.")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--working-tree", action="store_true", help="Scan tracked and non-ignored untracked files."
    )
    parser.add_argument(
        "--json", action="store_true", help="Output paths, categories and counts only."
    )
    args = parser.parse_args()
    try:
        root = Path(git(Path.cwd(), "rev-parse", "--show-toplevel").decode().strip())
        result = scan(root, args.working_tree)
    except (OSError, RuntimeError):
        print("Submission scan could not inspect this repository.", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for item in result["findings"]:
            print(f"{item['path']}:{item['line']} [{item['kind']}]")
        for item in result["errors"]:
            print(f"{item['path']} [scan_error:{item['kind']}]")
        print(
            f"Scope={result['scope']}; files={result['files']}; "
            f"findings={result['finding_count']}; errors={result['error_count']}; "
            f"binary_skipped={result['formats'].get('binary_skipped', 0)}"
        )
        if not result["files"] and not args.working_tree:
            print("No staged files. Use --working-tree for the current non-ignored workspace.")
    return 2 if result["error_count"] else 1 if result["finding_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
