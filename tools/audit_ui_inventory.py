"""Generate a static inventory, not a claim of browser/hardware test coverage."""
import argparse
from html.parser import HTMLParser
import json
from pathlib import Path
import re


class Controls(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []; self.button = None; self.headings = []; self.heading = None
    def handle_starttag(self, tag, attrs):
        attr = dict(attrs)
        if tag in {'button', 'input', 'select', 'textarea', 'a'} or any(k in attr for k in ('onclick', 'onchange', 'oninput')):
            row = {'line': self.getpos()[0], 'tag': tag, 'id': attr.get('id', ''),
                   'label': attr.get('aria-label') or attr.get('data-tooltip') or attr.get('title') or attr.get('placeholder') or '',
                   'action': attr.get('onclick') or attr.get('onchange') or attr.get('oninput') or attr.get('href') or '',
                   'type': attr.get('type', ''), 'disabled': 'disabled' in attr,
                   'coverage': 'static only; not an end-to-end test'}
            self.rows.append(row)
            if tag == 'button': self.button = row
        if tag in {'h1', 'h2', 'h3', 'h4'}:
            self.heading = {'line': self.getpos()[0], 'text': ''}; self.headings.append(self.heading)
    def handle_data(self, data):
        if self.button and not self.button['label']:
            self.button['label'] += data.strip()
        if self.heading: self.heading['text'] += data.strip() + ' '
    def handle_endtag(self, tag):
        if tag == 'button': self.button = None
        if tag in {'h1', 'h2', 'h3', 'h4'}: self.heading = None


def main():
    result = {}
    for path in sorted([*Path('templates').glob('*.html'), *Path('WebRTC_Meet/templates').glob('*.html')]):
        source = path.read_text()
        # Exclude script-generated markup here: it is inventoried separately.
        html = re.sub(r'<script\b[^>]*>.*?</script>', lambda m: '\n'*m[0].count('\n'), source, flags=re.S|re.I)
        parser = Controls(); parser.feed(html)
        names = set(re.findall(r'(?:async\s+)?function\s+(\w+)\s*\(', source))
        for row in parser.rows:
            match = re.match(r'(\w+)\s*\(', row['action'])
            row['handler'] = match[1] if match else None
            row['handler_declared'] = row['handler'] in names if row['handler'] else None
        result[str(path)] = {'controls': parser.rows, 'headings': parser.headings,
                             'dynamic_controls': [m[0] for script in re.findall(r'<script\b[^>]*>(.*?)</script>', source, re.S|re.I)
                              for m in re.finditer(r'<button\b[^>]*>', script)]}
    parser = argparse.ArgumentParser(); parser.add_argument('--output', default='docs/UI_CONTROL_INVENTORY.json')
    output = parser.parse_args().output
    Path(output).write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    missing = [r['handler'] for v in result.values() for r in v['controls'] if r['handler_declared'] is False]
    if missing:
        raise SystemExit('Undeclared inline handlers: ' + ', '.join(sorted(set(missing))))
    print(json.dumps({p: {'controls': len(v['controls']), 'dynamic_buttons': len(v['dynamic_controls']),
                         'undeclared_inline_handlers': sorted({r['handler'] for r in v['controls'] if r['handler_declared'] is False})}
                      for p, v in result.items()}, ensure_ascii=False))

if __name__ == '__main__':
    main()
