#!/usr/bin/env python3
"""Verify the installable APK, its public signing certificate, and Xposed metadata."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import subprocess
import zipfile

parser = argparse.ArgumentParser()
parser.add_argument('apk', type=Path)
parser.add_argument('--output', type=Path, default=Path('verification'))
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
root = Path(__file__).resolve().parents[1]
data = json.loads((root / 'localization/ko.json').read_text())
sdk = Path(os.environ.get('ANDROID_HOME') or os.environ['ANDROID_SDK_ROOT'])
versions = [p for p in (sdk / 'build-tools').iterdir() if (p / 'apksigner').exists()]
tools = max(versions, key=lambda p: tuple(int(n) for n in re.findall(r'\d+', p.name)))

def run(command):
    return subprocess.run(command, check=True, capture_output=True, text=True).stdout

signature = run([str(tools / 'apksigner'), 'verify', '--verbose', '--print-certs', str(args.apk)])
manifest = run([str(tools / 'aapt2'), 'dump', 'badging', str(args.apk)])
assert f"name='com.rikumi.colorosmod'" in manifest
assert f"versionCode='{data['version_code']}'" in manifest
assert f"versionName='{data['version_name']}'" in manifest
assert "application-label:'ColorOS Mod 한국어'" in manifest
assert 'application-debuggable' in manifest, 'This release is explicitly a debug build'
with zipfile.ZipFile(args.apk) as apk:
    for name in ('java_init.list', 'scope.list', 'module.prop'):
        assert apk.read('META-INF/xposed/' + name) == (root / 'app/src/main/resources/META-INF/xposed' / name).read_bytes()
    assert apk.read('assets/LICENSE') == (root / 'LICENSE').read_bytes()
    assert 'classes.dex' in apk.namelist()
(args.output / 'signature.txt').write_text(signature)
(args.output / 'apk-manifest.txt').write_text(manifest)
(args.output / 'apk-report.json').write_text(json.dumps({
    'status': 'passed', 'filename': args.apk.name, 'size_bytes': args.apk.stat().st_size,
    'sha256': hashlib.sha256(args.apk.read_bytes()).hexdigest(),
    'version_name': data['version_name'], 'version_code': data['version_code'],
    'package_id': 'com.rikumi.colorosmod', 'signing': 'CI-generated Android debug certificate',
    'xposed_metadata': 'unchanged', 'license': 'complete upstream MIT notice included',
}, ensure_ascii=False, indent=2) + '\n')
print(signature)
print('APK package, Korean label, version, Xposed metadata, license and signature verified.')
