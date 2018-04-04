extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.intersphinx',
    'sphinxcontrib.asyncio',
]

autoclass_content = 'both'
autodoc_member_order = 'bysource'

intersphinx_mapping = {
    'python': ('https://docs.python.org/3.6', None),
}

source_suffix = '.rst'
master_doc = 'index'

project = 'grpclib'
copyright = '2018, Vladimir Magamedov'
author = 'Vladimir Magamedov'

version = 'dev'
release = 'dev'

templates_path = []

html_theme = 'sphinx_rtd_theme'
html_static_path = ['_static']
