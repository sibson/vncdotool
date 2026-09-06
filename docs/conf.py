# flake8: noqa

from __future__ import annotations

extensions = ['sphinx.ext.autodoc', 'sphinx.ext.viewcode']
templates_path = ['_templates']
source_suffix = '.rst'
master_doc = 'index'

project = u'VNCDoTool'
copyright = u'2013-2024, Marc Sibson'

from vncdotool import __version__ as version
release = version

exclude_patterns = ['_build']
pygments_style = 'sphinx'

html_theme = 'nature'
html_theme_options = {
        "sidebarwidth": "250px"
}
html_static_path = ['_static']
html_css_files = ["custom.css"]
html_show_sourcelink = False
htmlhelp_basename = 'VNCDoTooldoc'

latex_elements: dict[str, str] = {}

latex_documents = [
  ('index', 'VNCDoTool.tex', u'VNCDoTool Documentation',
   u'Marc Sibson', 'manual'),
]

man_pages = [
    ('index', 'vncdotool', u'VNCDoTool Documentation',
     [u'Marc Sibson'], 1)
]

texinfo_documents = [
  ('index', 'VNCDoTool', u'VNCDoTool Documentation',
   u'Marc Sibson', 'VNCDoTool', 'One line description of project.',
   'Miscellaneous'),
]
