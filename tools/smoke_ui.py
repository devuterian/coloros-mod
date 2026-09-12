#!/usr/bin/env python3
"""Read-only emulator UI smoke test. Never enables features or restarts scopes."""
from pathlib import Path
import json
import re
import subprocess
import time
import xml.etree.ElementTree as ET

OUT = Path('verification/ui')
OUT.mkdir(parents=True, exist_ok=True)
PACKAGE = 'com.rikumi.colorosmod'
CATEGORIES = [
    ('home-screen', '홈 화면'), ('control-center', '제어 센터'),
    ('notifications', '알림 센터·상태 표시줄'), ('lockscreen', '잠금 화면'),
    ('hidden-apps', '숨긴 앱'), ('floating-windows', '플로팅 창'),
    ('gestures', '내비게이션·제스처'), ('storage', '저장 공간 관리'),
    ('disabled-apps', '사용 중지된 앱'),
]


def adb(*args, binary=False):
    result = subprocess.run(['adb', *args], check=True, capture_output=True, timeout=45)
    return result.stdout if binary else result.stdout.decode('utf-8', errors='replace')


def hierarchy():
    for attempt in range(4):
        try:
            adb('shell', 'uiautomator', 'dump', '/sdcard/window.xml')
            return ET.fromstring(adb('shell', 'cat', '/sdcard/window.xml'))
        except (ET.ParseError, subprocess.CalledProcessError):
            time.sleep(1)
    raise RuntimeError('Cannot read the emulator UI hierarchy')


def snapshot(name):
    tree = hierarchy()
    texts = []
    for node in tree.iter('node'):
        if node.attrib.get('package') != PACKAGE:
            continue
        for key in ('text', 'content-desc'):
            value = node.attrib.get(key, '')
            if re.search(r'[\u3400-\u9fff]', value):
                raise AssertionError(f'Untranslated UI text in {name}: {value}')
            if value:
                texts.append(value)
    if not texts:
        raise AssertionError(f'No visible application text: {name}')
    (OUT / f'{name}.xml').write_bytes(ET.tostring(tree, encoding='utf-8'))
    (OUT / f'{name}.png').write_bytes(adb('exec-out', 'screencap', '-p', binary=True))
    return texts


def home():
    adb('shell', 'am', 'force-stop', PACKAGE)
    adb('shell', 'am', 'start', '-W', '-n', PACKAGE + '/.MainActivity')
    time.sleep(2)


def open_category(label):
    for _ in range(6):
        tree = hierarchy()
        for node in tree.iter('node'):
            if node.attrib.get('text') == label and node.attrib.get('package') == PACKAGE:
                coords = list(map(int, re.findall(r'\d+', node.attrib['bounds'])))
                x1, y1, x2, y2 = coords
                if y2 > y1 and x2 > x1:
                    adb('shell', 'input', 'tap', str((x1+x2)//2), str((y1+y2)//2))
                    time.sleep(1)
                    return
        adb('shell', 'input', 'swipe', '540', '1740', '540', '700', '450')
        time.sleep(1)
    raise AssertionError(f'Category not found: {label}')


adb('shell', 'wm', 'size', '1080x2160')
adb('shell', 'wm', 'density', '480')
adb('logcat', '-c')
results = []
for mode in ('no', 'yes'):
    theme = 'light' if mode == 'no' else 'dark'
    adb('shell', 'cmd', 'uimode', 'night', mode)
    home()
    results.append({'screen': theme + '-home', 'text': snapshot(theme + '-home')})
    for slug, label in CATEGORIES:
        home()
        open_category(label)
        name = theme + '-' + slug
        texts = snapshot(name)
        if label not in texts:
            raise AssertionError(f'Expected screen title not present: {label}')
        results.append({'screen': name, 'text': texts})
        for step in range(2):
            adb('shell', 'input', 'swipe', '540', '1740', '540', '650', '450')
            time.sleep(0.4)
            snapshot(name + '-scroll-' + str(step + 1))
logs = adb('logcat', '-d', '-s', 'AndroidRuntime:E')
(OUT / 'android-runtime.log').write_text(logs)
if 'FATAL EXCEPTION' in logs:
    raise AssertionError('AndroidRuntime reported a crash; see android-runtime.log')
(OUT / 'ui-report.json').write_text(json.dumps({
    'status': 'passed', 'viewport_dp': [360, 720], 'themes': ['light', 'dark'],
    'screens': results, 'feature_toggles_changed': False,
    'scope': 'Generic Android emulator UI only; ColorOS/LSPosed hooks not device-tested',
}, ensure_ascii=False, indent=2), encoding='utf-8')
print('Passed: main screen and all 9 categories in light/dark mode; no features enabled.')
