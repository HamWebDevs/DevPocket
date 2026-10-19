import tempfile
import unittest
from pathlib import Path
from unittest import mock

from devpocket.assetguard import analyse
from devpocket.assetrefs import css_resources
from devpocket.engine import execute, gated_exit


class CSSResourceTests(unittest.TestCase):
    def test_literal_imports_urls_and_source_lines(self):
        css = b'/* url(ignored.png) */\n@import "theme.css" layer(ui);\n@import url(fonts.css);\na{background:URL("hero.png");content:"url(fake.png)"}'
        result = css_resources(css)
        self.assertEqual(result.references, [('theme.css', 2), ('fonts.css', 3), ('hero.png', 4)])
        self.assertEqual(result.unparsed, 0)

    def test_escaped_names_paths_and_string_line_continuations(self):
        css = b'a{src:u\\72l(font\\20 face.woff2);background:url(image\\(1\\).png)}\n@import "th\\\neme.css";'
        self.assertEqual(css_resources(css).references, [('font face.woff2', 1), ('image(1).png', 1), ('theme.css', 2)])

    def test_strings_comments_namespace_and_non_url_functions_are_not_fetches(self):
        css = b'@namespace svg "https://example.invalid/ns"; @namespace url(relative-namespace); /* @import "no.css" */ a {content:"url(fake.png)";background:image-set("candidate.png" 1x);x:some-url(fake.png)}'
        self.assertEqual(css_resources(css).references, [])
        self.assertEqual(css_resources(b'@namespace svg url(ns;part);a{x:url(real.png)}').references, [('real.png', 1)])

    def test_fragment_and_empty_references_are_not_missing_files(self):
        result = css_resources(b'a{filter:url(#blur);x:url("");y:url(  )}')
        self.assertEqual(result.references, [])
        self.assertEqual(result.fragments, 3)

    def test_invalid_or_computed_urls_report_incomplete_coverage(self):
        for css in [b'a{x:url(var(--image))}', b'a{x:url(a b.png)}', b'a{x:url("unterminated)', b'/* unfinished', b'a{x:url(a\\\nb)}']:
            with self.subTest(css=css):
                self.assertGreater(css_resources(css).unparsed, 0)

    def test_utf8_bom_charset_and_unsupported_encodings(self):
        self.assertEqual(css_resources(b'\xef\xbb\xbf@charset "UTF-8";a{x:url(ok.png)}').references, [('ok.png', 1)])
        for css in [b'@charset "windows-1252";a{x:url(x.png)}', b'\xff\xfeCSS', b'a{x:url(\xff.png)}']:
            result = css_resources(css)
            self.assertFalse(result.references)
            self.assertGreater(result.unparsed, 0)

    def test_crlf_lines_and_reference_limit(self):
        self.assertEqual(css_resources(b'\r\n\r\na{x:url(x.png)}').references, [('x.png', 3)])
        with self.assertRaisesRegex(ValueError, 'inspection limit'):
            css_resources(b'a{x:url(a);y:url(b)}', maximum=1)


class CSSBuildTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def write(self, name, text='asset'):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        return path

    def test_import_chain_fonts_and_images_resolve_from_each_stylesheet(self):
        self.write('index.html', '<base href="/site/"><link rel="stylesheet" href="css/main.css">')
        self.write('css/main.css', '@import "nested/theme.css";a{background:url(../images/hero.png?version=1#x)}')
        self.write('css/nested/theme.css', '@font-face{src:url(../../fonts/font.woff2)}')
        self.write('images/hero.png', 'image')
        self.write('fonts/font.woff2', 'font')
        report = analyse(self.root, public_path='/site/')
        self.assertFalse(report['findings'])
        self.assertEqual(report['summary']['css_stylesheets'], 2)
        self.assertEqual(report['summary']['css_resource_references'], 3)
        self.assertEqual(report['summary']['local_resource_references'], 4)

    def test_missing_font_is_located_and_flows_into_sdk_gates(self):
        self.write('css/site.css', 'a{color:red}\n@font-face{src:url(../fonts/missing.woff2)}')
        report = analyse(self.root)
        issue = report['findings'][0]
        self.assertEqual((issue['rule'], issue['path'], issue['line']), ('missing-build-resource', 'css/site.css', 2))
        structured = execute('assetguard', {'path': '.'}, self.root)
        self.assertEqual(gated_exit(structured, 'error'), 1)
        self.assertTrue(any(f['path'] == 'css/site.css' for f in structured['findings']))

    def test_css_has_its_own_base_and_rejects_encoded_mount_escape(self):
        self.write('css/main.css', 'a{x:url(/site/%2e%2e/private.png);y:url(/site/%5csecret.png)}')
        rules = {f['rule'] for f in analyse(self.root, public_path='/site/')['findings']}
        self.assertEqual(rules, {'resource-outside-public-path', 'invalid-resource-url'})

    def test_remote_and_embedded_resources_are_counted_without_fetching(self):
        self.write('main.css', 'a{x:url(https://cdn.example.invalid/p.png);y:url("data:image/svg+xml,<svg></svg>");z:url(#mask)}')
        report = analyse(self.root)
        self.assertFalse(report['findings'])
        self.assertEqual(report['summary']['external_resource_references'], 2)
        self.assertEqual(report['summary']['css_fragment_references'], 1)

    def test_private_css_like_file_contents_are_never_read(self):
        private = self.write('secrets.css', 'NEVER-READ')
        self.write('main.css', 'a{x:url(secrets.css)}')
        original = Path.open
        with mock.patch.object(Path, 'open', lambda p, *a, **k: (_ for _ in ()).throw(AssertionError('private read')) if p == private else original(p, *a, **k)):
            report = analyse(self.root)
        self.assertNotIn('NEVER-READ', str(report))
        self.assertIsNone(next(f for f in report['snapshot']['files'] if f['path'] == private.name)['sha256'])

    def test_malformed_css_warns_without_claiming_complete_coverage(self):
        self.write('main.css', 'a{x:url(var(--image))}')
        report = analyse(self.root)
        self.assertIn('css-reference-coverage', {f['rule'] for f in report['findings']})
        self.assertGreater(report['summary']['css_unparsed_tokens'], 0)

    def test_aggregate_css_and_html_reference_budget_is_shared(self):
        self.write('main.css', 'a{x:url(a.png);y:url(a.png)}')
        self.write('index.html', '<img src="a.png">')
        self.write('a.png')
        with mock.patch('devpocket.assetguard.MAX_REFERENCES', 2), self.assertRaisesRegex(ValueError, 'resource references'):
            analyse(self.root)
