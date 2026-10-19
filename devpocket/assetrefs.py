"""Bounded literal CSS URL inspection, without evaluating CSS or fetching assets.

Recognises url() and string @import references. This is a token scanner, not a
stylesheet validator; dynamic image-set strings and computed values are outside
its coverage. Comments, strings and CSS escapes are handled explicitly.
"""
from __future__ import annotations


class CSSResources:
    def __init__(self, text, maximum=20000):
        self.text = text.replace('\r\n', '\n').replace('\r', '\n').replace('\f', '\n').replace('\0', '\ufffd')
        self.maximum = maximum
        self.index, self.line = 0, 1
        self.references, self.unparsed, self.fragments = [], 0, 0

    def advance(self, count=1):
        end = min(len(self.text), self.index + count)
        self.line += self.text.count('\n', self.index, end)
        self.index = end

    def comment(self):
        end = self.text.find('*/', self.index + 2)
        if end < 0:
            self.unparsed += 1
            self.advance(len(self.text) - self.index)
        else:
            self.advance(end + 2 - self.index)

    def spaces(self, comments=True):
        while self.index < len(self.text):
            if self.text[self.index] in ' \t\n':
                self.advance()
            elif comments and self.text.startswith('/*', self.index):
                self.comment()
            else:
                break

    def escape(self):
        self.advance()  # backslash
        if self.index == len(self.text):
            return '\ufffd'
        char = self.text[self.index]
        if char in '0123456789abcdefABCDEF':
            start = self.index
            while self.index < min(start + 6, len(self.text)) and self.text[self.index] in '0123456789abcdefABCDEF':
                self.advance()
            number = int(self.text[start:self.index], 16)
            if self.index < len(self.text) and self.text[self.index] in ' \t\n':
                self.advance()
            return chr(number) if 0 < number <= 0x10ffff and not 0xd800 <= number <= 0xdfff else '\ufffd'
        self.advance()
        return '' if char == '\n' else char

    def identifier(self):
        value = []
        while self.index < len(self.text):
            char = self.text[self.index]
            if char.isalnum() or char in '_-' or ord(char) >= 128:
                value.append(char)
                self.advance()
            elif char == '\\' and self.index + 1 < len(self.text) and self.text[self.index + 1] != '\n':
                value.append(self.escape())
            else:
                break
        return ''.join(value).lower()

    def string(self):
        quote = self.text[self.index]
        self.advance()
        value = []
        while self.index < len(self.text):
            char = self.text[self.index]
            if char == quote:
                self.advance()
                return ''.join(value), True
            if char == '\n':
                return '', False
            if char == '\\':
                value.append(self.escape())
            else:
                value.append(char)
                self.advance()
        return '', False

    def add(self, value, line):
        if not value or value.startswith('#'):
            self.fragments += 1
            return
        if len(self.references) >= self.maximum:
            raise ValueError('CSS resource references exceed the inspection limit')
        self.references.append((value, line))

    def url(self, line):
        self.advance()  # opening parenthesis
        self.spaces(comments=False)
        valid = True
        if self.index < len(self.text) and self.text[self.index] in '\"\'':
            value, valid = self.string()
            self.spaces()
        else:
            pieces = []
            while self.index < len(self.text):
                char = self.text[self.index]
                if char == ')':
                    break
                if char in ' \t\n':
                    self.spaces(comments=False)
                    break
                if char in '\"\'(' or ord(char) < 32 or ord(char) == 127:
                    valid = False
                    break
                if char == '\\':
                    if self.index + 1 >= len(self.text) or self.text[self.index + 1] == '\n':
                        valid = False
                        break
                    pieces.append(self.escape())
                else:
                    pieces.append(char)
                    self.advance()
            value = ''.join(pieces)
        if valid and self.index < len(self.text) and self.text[self.index] == ')':
            self.advance()
            self.add(value, line)
        else:
            self.unparsed += 1
            # Recover a bad-url token without interpreting its contents as URLs.
            while self.index < len(self.text) and self.text[self.index] != ')':
                if self.text[self.index] == '\\':
                    self.escape()
                else:
                    self.advance()
            if self.index < len(self.text):
                self.advance()

    def namespace(self):
        # Namespace URIs identify XML namespaces; they are never fetched assets.
        depth = 0
        while self.index < len(self.text):
            char = self.text[self.index]
            if self.text.startswith('/*', self.index):
                self.comment()
            elif char in '\"\'':
                _, valid = self.string()
                self.unparsed += int(not valid)
            elif char == '\\':
                self.escape()
            elif char == '{' or char == ';' and depth == 0:
                if char == ';':
                    self.advance()
                return
            else:
                depth += int(char == '(') - int(char == ')' and depth > 0)
                self.advance()

    def scan(self):
        while self.index < len(self.text):
            char, line = self.text[self.index], self.line
            if self.text.startswith('/*', self.index):
                self.comment()
            elif char in '\"\'':
                _, valid = self.string()
                self.unparsed += int(not valid)
            elif char == '@':
                self.advance()
                rule = self.identifier()
                if rule == 'namespace':
                    self.namespace()
                elif rule == 'import':
                    self.spaces()
                    if self.index < len(self.text) and self.text[self.index] in '\"\'':
                        value, valid = self.string()
                        if valid:
                            self.add(value, line)
                        else:
                            self.unparsed += 1
            elif char.isalpha() or char in '_-\\' or ord(char) >= 128:
                before = self.index
                name = self.identifier()
                if name == 'url' and self.index < len(self.text) and self.text[self.index] == '(':
                    self.url(line)
                elif self.index == before:
                    self.advance()
            else:
                self.advance()
        return self


def css_resources(payload, maximum=20000):
    if payload.startswith((b'\xff\xfe', b'\xfe\xff')):
        result = CSSResources('', maximum)
        result.unparsed = 1
        return result
    try:
        text = payload.decode('utf-8-sig')
    except UnicodeError:
        result = CSSResources('', maximum)
        result.unparsed = 1
        return result
    if text.startswith('@charset "'):
        end = text.find('"', 10)
        if end >= 0 and text[10:end].lower() not in {'utf-8', 'utf8'}:
            result = CSSResources('', maximum)
            result.unparsed = 1
            return result
    return CSSResources(text, maximum).scan()
