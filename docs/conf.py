extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.intersphinx',
]

autoclass_content = 'both'
autodoc_member_order = 'bysource'

intersphinx_mapping = {
    'python': ('https://docs.python.org/3', None),
}

source_suffix = '.rst'
master_doc = 'index'

project = 'grpclib'
copyright = '2019, Volodymyr Magamedov'
author = 'Volodymyr Magamedov'

templates_path = []

html_theme = 'sphinx_rtd_theme'
html_static_path = ['_static']
html_theme_options = {
    'display_version': False,
}


def setup(app):
    app.add_stylesheet('style.css')
