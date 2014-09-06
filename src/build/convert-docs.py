#!/usr/bin/python
#
# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# Tool to convert Markdown files to HTML.
#
# For usage run 'python src/build/convert-docs.py --help
#

import argparse
import cgi
import markdown
import os
import re
import string
import sys


_HTML_TEMPLATE = string.Template("""
<head>
<title>$TITLE</title>
<style type="text/css">
body {
  font-family: sans-serif;
  line-height: 1.6;
  margin: 20px auto;
  width: 75%;
}
pre {
  background: #eee;
  border-radius: 4px;
  padding: 12px;
}
div#breadcrumb {
  color: #666;
  font-weight: bold;
  text-align: right;
}
div#breadcrumb a {
  color: #666;
  text-decoration: none;
}
div#breadcrumb a:hover {
  text-decoration: underline;
}
</style>
</head>
<body>
<div id="breadcrumb">
<a href="index.html">Documentation</a> $BREADCRUMB_LEAF
</div>
</div>
<h1>$TITLE</h1>
$CONTENT
</body>
</html>
""".lstrip())


def _read(input_file_name):
  """Read a Markdown file and return its title and content."""

  with open(input_file_name, 'r') as f:
    try:
      title, second_line, text = f.read().split('\n', 2)
    except ValueError:
      sys.exit('%s: A document should contain at least 3 lines.' %
               input_file_name)

  # The first line should be the document title.
  if not title:
    sys.exit('%s: A non-blank title line as the first line is required.' %
             input_file_name)

  # The next line should be the first-level header marker.
  if not re.match(r'=+$', second_line):
    sys.exit('%s: The second line should be one or more = characters as the '
             'first line should be a top level header giving a title to the '
             'document.' % input_file_name)

  return title, text


def _convert(input_file_name):
  """Convert a Markdown file into HTML format.

  Return the document title and content.
  """

  title, text = _read(input_file_name)

  # Use 'toc' (Table of Contents) extension.
  text = '[TOC]\n' + text
  content = markdown.markdown(text, extensions=['toc'])

  template_dict = {}
  template_dict['BREADCRUMB_LEAF'] = '&raquo; ' + cgi.escape(title)
  template_dict['CONTENT'] = content
  template_dict['TITLE'] = cgi.escape(title)
  output = _HTML_TEMPLATE.substitute(template_dict)

  return title, output


def _generate_index(document_map):
  """Generate index.html content from the given document map."""

  toc = ['<ul>']
  for title, file_name in sorted(document_map):
    toc.append('<li><a href="%s">%s</a></li>' %
               (cgi.escape(file_name, quote=True),
                cgi.escape(title)))
  toc.append('</ul>')
  content = '\n'.join(toc)

  title = 'App Runtime for Chrome Documentation'
  template_dict = {}
  # Do not show the breadcrumb leaf as this is the top level document.
  template_dict['BREADCRUMB_LEAF'] = ''
  template_dict['CONTENT'] = content
  template_dict['TITLE'] = cgi.escape(title)
  output = _HTML_TEMPLATE.substitute(template_dict)

  return output


def main():
  description = 'Tool to convert Markdown files to HTML.'
  parser = argparse.ArgumentParser(description=description)
  parser.add_argument('--output-dir',
                      required=True,
                      help='Specify the directory to store test ouput files.')
  parser.add_argument('input_file_names',
                      help='Specify the input file names in Markdown format.',
                      metavar='FILE',
                      nargs='*')
  args = parser.parse_args()
  output_dir = args.output_dir

  if not os.path.exists(output_dir):
    os.makedirs(output_dir)

  document_map = []  # Map of document title to base HTML file name.
  for input_file_name in args.input_file_names:
    name = os.path.splitext(os.path.basename(input_file_name))[0]
    output_file_name = os.path.join(output_dir, name + '.html')
    title, html = _convert(input_file_name)
    document_map.append((title, os.path.basename(output_file_name)))
    with open(output_file_name, 'w') as f:
      f.write(html)

  html = _generate_index(document_map)
  with open(os.path.join(output_dir, 'index.html'), 'w') as f:
    f.write(html)

if __name__ == '__main__':
  sys.exit(main())
