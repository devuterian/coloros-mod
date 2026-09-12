#!/usr/bin/env python3
"""Apply and audit the reviewed Korean-only translation of upstream 1.0.36.

Only complete, reviewed string literals and narrowly scoped display labels change.
Chinese ROM matching patterns, preference keys, shell commands, reflection targets,
and every other code token are protected by per-file canonical SHA-256 hashes.
No network, credentials, Android SDK, or third-party Python modules are required.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
TOKEN = re.compile(
    r'//[^\n]*|/\*.*?\*/|""".*?"""|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', re.S
)
CJK = re.compile(r'[\u3400-\u9fff]')


def read(path: Path) -> str:
    return path.read_bytes().decode('utf-8')


def decoded(token: str) -> str | None:
    if not token.startswith('"') or token.startswith('"""'):
        return None
    try:
        return json.loads(token)
    except ValueError:
        return None


def canonical(path: str, text: str, data: dict) -> str:
    # Undo only the explicitly approved, display-only edits before comparing code.
    for edit in data['display_edits']:
        if edit['path'] == path:
            text = text.replace(edit['after'], edit['before'])
    localized = set(data['strings']) | set(data['strings'].values())
    def normalize(match: re.Match) -> str:
        token = match[0]
        if token.startswith(('//', '/*')):
            return ''
        if decoded(token) in localized:
            return '"<translated-ui-text>"'
        return token
    return TOKEN.sub(normalize, text.replace('\r\n', '\n'))


def code_paths() -> list[Path]:
    return sorted(p for p in (ROOT / 'app/src/main/java').rglob('*')
                  if p.suffix in ('.kt', '.java'))


def apply(data: dict) -> None:
    # Validate all code before writing any changes. A changed upstream needs review.
    for path in code_paths():
        relative = path.relative_to(ROOT).as_posix()
        expected = data['code_sha256'].get(relative)
        actual = hashlib.sha256(canonical(relative, read(path), data).encode()).hexdigest()
        if actual != expected:
            raise ValueError(f'Unreviewed code change: {relative}')
    translated = 0
    for path in code_paths():
        relative = path.relative_to(ROOT).as_posix()
        text = read(path)
        def replace(match: re.Match) -> str:
            nonlocal translated
            value = decoded(match[0])
            if value in data['strings']:
                translated += 1
                return json.dumps(data['strings'][value], ensure_ascii=False)
            return match[0]
        text = TOKEN.sub(replace, text)
        for edit in data['display_edits']:
            if edit['path'] != relative:
                continue
            if text.count(edit['before']) == 1:
                text = text.replace(edit['before'], edit['after'], 1)
            elif text.count(edit['after']) != 1:
                raise ValueError(f'Display edit no longer matches: {relative}: {edit["before"]}')
        path.write_bytes(text.encode('utf-8'))
    resource = ROOT / 'app/src/main/res/values/strings.xml'
    text = read(resource)
    for name, value in data['resource_strings'].items():
        pattern = rf'(<string name="{re.escape(name)}">).*?(</string>)'
        text, count = re.subn(pattern, lambda m: m[1] + value + m[2], text, flags=re.S)
        if count != 1:
            raise ValueError(f'Resource is missing or duplicated: {name}')
    resource.write_bytes(text.encode('utf-8'))
    gradle = ROOT / 'app/build.gradle'
    text = read(gradle)
    text, codes = re.subn(r'versionCode \d+', f'versionCode {data["version_code"]}', text)
    text, names = re.subn(r"versionName '[^']+'", f"versionName '{data['version_name']}'", text)
    if codes != 1 or names != 1:
        raise ValueError('Version metadata must occur exactly once')
    gradle.write_bytes(text.encode('utf-8'))
    assets = ROOT / 'app/src/main/assets'
    assets.mkdir(exist_ok=True)
    (assets / 'LICENSE').write_bytes((ROOT / 'LICENSE').read_bytes())
    print(f'Applied {translated} reviewed source-string replacements.')


def check(data: dict) -> dict:
    errors = []
    preserved = []
    paths = code_paths()
    actual_paths = {p.relative_to(ROOT).as_posix() for p in paths}
    if actual_paths != set(data['code_sha256']):
        errors.append('Source file inventory differs from the reviewed upstream snapshot')
    for path in paths:
        relative = path.relative_to(ROOT).as_posix()
        text = read(path)
        digest = hashlib.sha256(canonical(relative, text, data).encode()).hexdigest()
        if digest != data['code_sha256'].get(relative):
            errors.append(f'Non-localization code changed: {relative}')
        for match in TOKEN.finditer(text):
            token = match[0]
            if not token.startswith('"') or not CJK.search(token):
                continue
            value = decoded(token)
            if value in data['preserved_matchers'].get(relative, []):
                preserved.append({'path': relative, 'literal': value})
            else:
                errors.append(f'Untranslated literal: {relative}: {token}')
        for edit in data['display_edits']:
            if edit['path'] == relative and text.count(edit['after']) != 1:
                errors.append(f'Missing/duplicate localized display label: {relative}')
    expected_preserved = sum(len(values) for values in data['preserved_matchers'].values())
    if len(preserved) != expected_preserved:
        errors.append('An upstream Chinese detection pattern changed or disappeared')
    resource = ET.parse(ROOT / 'app/src/main/res/values/strings.xml').getroot()
    strings = {e.attrib['name']: e.text for e in resource.findall('string')}
    for name, expected in data['resource_strings'].items():
        if strings.get(name) != expected:
            errors.append(f'Untranslated manifest resource: {name}')
    for path in (ROOT / 'app/src/main/res').rglob('*.xml'):
        tree = ET.parse(path)
        for element in tree.iter():
            if element.tag in ('string', 'item') and CJK.search(element.text or ''):
                errors.append(f'Untranslated resource text: {path.relative_to(ROOT)}')
    gradle = read(ROOT / 'app/build.gradle')
    for expected in (f'versionCode {data["version_code"]}',
                     f"versionName '{data['version_name']}'",
                     "applicationId 'com.rikumi.colorosmod'"):
        if expected not in gradle:
            errors.append(f'Unexpected build metadata: {expected}')
    if (ROOT / 'app/src/main/assets/LICENSE').read_bytes() != (ROOT / 'LICENSE').read_bytes():
        errors.append('The APK must retain the complete upstream MIT license')
    if errors:
        raise ValueError('\n'.join(errors))
    return {
        'version': data['version_name'], 'status': 'passed',
        'reviewed_translation_entries': len(data['strings']),
        'reviewed_display_edits': len(data['display_edits']),
        'protected_source_files': len(paths),
        'untranslated_user_facing_cjk_literals': 0,
        'preserved_internal_matchers': preserved,
        'package_id': 'com.rikumi.colorosmod',
        'device_hook_testing': 'Not performed by this static audit',
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--apply', action='store_true')
    group.add_argument('--check', action='store_true')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    try:
        data = json.loads(read(ROOT / 'localization/ko.json'))
        if args.apply:
            apply(data)
        report = check(data)
        output = json.dumps(report, ensure_ascii=False, indent=2) + '\n'
        print(output)
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(output, encoding='utf-8')
        return 0
    except (ValueError, OSError, ET.ParseError) as error:
        print(f'Korean localization audit failed: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
