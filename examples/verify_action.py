"""Check composite Action outputs, including artifacts from an intentionally failed gate."""
import json
import os
from pathlib import Path


def main():
    for prefix, expected in (('PASS', 0), ('FAIL', 1), ('WORKSPACE', 0)):
        report = json.loads(Path(os.environ[prefix + '_REPORT']).read_text(encoding='utf-8'))
        sarif = json.loads(Path(os.environ[prefix + '_SARIF']).read_text(encoding='utf-8'))
        assert report['exit_code'] == expected, report
        assert sarif['version'] == '2.1.0'
    assert os.environ.get('FAIL_OUTCOME') == 'failure'
    assert os.environ.get('FAIL_EXIT') == '1'
    print('Composite Action verified: project/workspace checks, isolated install, expected failure, JSON/SARIF outputs and propagated gate status.')


if __name__ == '__main__': main()
