"""Validate built distributions and prepare GitHub release notes/checksums."""
from __future__ import annotations

import argparse
from email.parser import BytesParser
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import tomllib
import zipfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--title', required=True)
    parser.add_argument('--dist', default='dist')
    parser.add_argument('--metadata-only', action='store_true')
    args = parser.parse_args()
    project = tomllib.loads(Path('pyproject.toml').read_text(encoding='utf-8'))['project']
    version, name = project['version'], project['name']
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('This workflow publishes final X.Y.Z versions only')
    if any(ord(c) < 32 for c in args.title):
        raise ValueError('Release title must be a single line')
    tag, title = 'v' + version, args.title + ' v' + version
    if os.environ.get('GITHUB_REF_TYPE') == 'tag' and os.environ.get('GITHUB_REF_NAME') != tag:
        raise ValueError('The pushed tag does not match the package version')
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    result = {'tag': tag, 'title': title, 'version': version, 'package': name, 'commit': commit}
    output_path = os.environ.get('GITHUB_OUTPUT')
    if output_path:
        with Path(output_path).open('a', encoding='utf-8') as output:
            for key in ('tag', 'title', 'version', 'commit'):
                output.write(key + '=' + result[key] + '\n')
    if args.metadata_only:
        print(json.dumps(result))
        return 0
    dist = Path(args.dist)
    wheels, sources = sorted(dist.glob('*.whl')), sorted(dist.glob('*.tar.gz'))
    if len(wheels) != 1 or len(sources) != 1:
        raise ValueError('Expected exactly one wheel and one source distribution')
    with zipfile.ZipFile(wheels[0]) as archive:
        candidates = [n for n in archive.namelist() if n.endswith('.dist-info/METADATA')]
        if len(candidates) != 1:
            raise ValueError('Wheel metadata is missing or ambiguous')
        wheel_metadata = BytesParser().parsebytes(archive.read(candidates[0]))
    with tarfile.open(sources[0], 'r:gz') as archive:
        candidates = [m for m in archive.getmembers() if m.name.count('/') == 1 and m.name.endswith('/PKG-INFO')]
        if len(candidates) != 1:
            raise ValueError('Source distribution metadata is missing or ambiguous')
        source_metadata = BytesParser().parsebytes(archive.extractfile(candidates[0]).read())
    normalize = lambda text: re.sub(r'[-_.]+', '-', text).lower()
    for metadata in (wheel_metadata, source_metadata):
        if metadata['Version'] != version or normalize(metadata['Name']) != normalize(name):
            raise ValueError('Distribution name/version does not match pyproject.toml')
    changelog = Path('CHANGELOG.md').read_text(encoding='utf-8')
    match = re.search(r'^## ' + re.escape(version) + r'(?:\s[^\n]*)?\n(.*?)(?=^## |\Z)', changelog, re.M | re.S)
    if not match:
        raise ValueError('The current version needs a changelog section')
    notes = match[1].strip()
    notes += '\n\n## Install\n\nRequires Python ' + project['requires-python'] + '. No runtime dependencies.\n\n```bash\npython -m pip install ./' + wheels[0].name + '\n```\n'
    if name == 'reclaimlab-toolkit':
        notes += '\nLive recording supports Windows and Linux. Offline analysis/reports also work on macOS. Timer wake delay is not measured GUI input latency. DevPocket integration is optional.\n'
    notes += '\n## Downloads and verification\n\nThe wheel installs directly; the source distribution builds from source. GitHub also provides source archives for the tagged commit. `SHA256SUMS` covers both uploaded package files.\n\n```bash\nsha256sum -c SHA256SUMS\n```\n\nBuilt from commit `' + commit + '`. Package metadata, the full unittest suite and installed-wheel smoke checks are verified by the release workflow. This is a GitHub release; the packages are not uploaded to PyPI.\n'
    (dist / 'RELEASE-NOTES.md').write_text(notes, encoding='utf-8')
    assets = [*wheels, *sources]
    checksums = ''.join(hashlib.sha256(asset.read_bytes()).hexdigest() + '  ' + asset.name + '\n' for asset in sorted(assets))
    (dist / 'SHA256SUMS').write_text(checksums, encoding='utf-8')
    result['assets'] = [asset.name for asset in assets] + ['SHA256SUMS']
    (dist / 'release-meta.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
