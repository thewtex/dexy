from datetime import datetime
from dexy.reporters.output import OutputReporter
from dexy.utils import dict_from_string
from dexy.utils import file_exists
from dexy.utils import iter_paths
from dexy.utils import reverse_iter_paths
from jinja2 import Environment
from jinja2 import FileSystemLoader
import dexy.exceptions
import dexy.filters.templating_plugins
import jinja2
import operator
import os
import posixpath

class Navigation(object):
    def __init__(self):
        # Lookup table for first pass of gathering info.
        self.lookup_table = {}

        self.nodes = {}
        self.root = None

    def populate_lookup_table(self, batch):
        for data in batch:
            if not data.output_name():
                continue

            parent_dir = "/" + os.path.dirname(data.output_name())
            if not self.lookup_table.has_key(parent_dir):
                self.lookup_table[parent_dir] = {'docs' : []}

            if data.is_canonical_output():
                self.lookup_table[parent_dir]['docs'].append(data)

            if data.is_index_page():
                self.lookup_table[parent_dir]['index-page'] = data

    def walk(self):
        """
        Build nodes dict from already-populated lookup table.
        """
        for path, info in self.lookup_table.iteritems():
            parent = None
            ancestors = []
            level = 0
            for parent_path in iter_paths(path):
                if not self.nodes.has_key(parent_path):
                    node = Node(parent_path, parent, [])
                    node.level = level
                    self.nodes[parent_path] = node
                    if parent:
                        parent.children.append(node)

                    if not self.root and parent_path == '/':
                        self.root = node

                parent = self.nodes[parent_path]
                ancestors.append(parent)
                level += 1

            assert parent.location == path
            parent.ancestors = ancestors
            parent.docs = info['docs']
            if info.has_key('index-page'):
                parent.index_page = info['index-page']

    def debug(self):
        """
        Returns a dump of useful information.
        """
        info = []
        for path, node in self.nodes.iteritems():
            info.append('')
            info.append("node: %s" % path)

            if node.index_page:
                info.append("  index-page:")
                info.append("    %s" % node.index_page.key)
                info.append('')
            else:
                info.append("  no index page.")
                info.append('')

            info.append("  docs:")
            for child in node.docs:
                info.append("    %s" % child.key)
            info.append('')

            info.append("  children:")
            for child in node.children:
                info.append("    %s" % child.location)
            info.append('')
        return "\n".join(info)

class Node(object):
    """
    Wrapper class for a location in the site hierarchy.
    """
    def __init__(self, location, parent, children):
        if parent:
            assert isinstance(parent, Node)
        if children:
            assert isinstance(children[0], Node)
        self.location = location
        self.parent = parent
        self.children = children
        self.ancestors = []
        self.docs = []
        self.index_page = None

    def __lt__(self, other):
        return self.location < other.location

    def __repr__(self):
        return "Node(%s)" % self.location

    def has_children_with_index_pages(self):
        return any(node.index_page for node in self.children)

    def breadcrumbs(self, divider = " &gt; "):
        return divider.join("""<a href="%s">%s</a>""" % (node.location, node.index_page.title()) for node in self.ancestors if node.index_page)

class WebsiteReporter(OutputReporter):
    """
    Applies a template to create a website from your dexy output.

    Templates are applied to all files with .html extension which don't already
    contain "<head" or "<body" tags.
    """
    aliases = ['ws']
    _other_class_settings = {
            'doc' : {
                'ws-template' : ("""Key of template to apply for rendering in
                website.  Setting of 'None' will use default template, 'False'
                will force no template to be used.""",
                None)
                }
            }

    _settings = {
            "dir" : "output-site",
            "default-template" : ("Path to the default template to apply.", "_template.html"),
            "default" : False
            }

    def apply_and_render_template(self, doc):
        # Figure out which template to use.
        ws_template = doc.setting('ws-template')
        if ws_template and not isinstance(ws_template, bool):
            template_file = ws_template
        else:
            template_file = self.setting('default-template')

        # Look for a file named template_file in nearest parent dir to document.
        template_path = None
        for subpath in reverse_iter_paths(doc.name):
            template_path = os.path.join(subpath, template_file)
            if file_exists(template_path):
                break

        if not template_path:
            raise dexy.exceptions.UserFeedback("no template path for %s" % doc.key)
        else:
            self.log_debug("  using template %s for %s" % (template_path, doc.key))

        # Populate template environment
        env = Environment(undefined=jinja2.StrictUndefined)

        dirs = [".", os.path.dirname(__file__), os.path.dirname(template_path)]
        env.loader = FileSystemLoader(dirs)

        self.log_debug("  loading template at %s" % template_path)
        template = env.get_template(template_path)

        current_dir = posixpath.dirname(doc.output_data().output_name())
        parent_dir = os.path.split(current_dir)[0]

        env_data = self.run_plugins()

        navigation = {
                }

        env_data.update({
                'content' : doc.output_data(),
                'locals' : locals,
                'navigation' : navigation,
                'nav' : self._navobj.nodes["/%s" % current_dir],
                'root' : self._navobj.nodes["/"],
                'navobj' : self._navobj,
                'page_title' : doc.output_data().title(),
                'parent_dir' : parent_dir,
                'current_dir' : current_dir,
                's' : doc.output_data(),
                'source' : doc.output_data().output_name(),
                'template_source' : template_path,
                'wrapper' : self.wrapper,
                'year' : datetime.now().year
                })

        if self.wrapper.globals:
            env_data.update(dict_from_string(self.wrapper.globals))

        fp = os.path.join(self.setting('dir'), doc.output_data().output_name()).replace(".json", ".html")

        parent_dir = os.path.dirname(fp)
        try:
            os.makedirs(os.path.dirname(fp))
        except os.error:
            pass

        self.log_debug("  writing to %s" % (fp))
        template.stream(env_data).dump(fp, encoding="utf-8")

    def run(self, wrapper):
        self.wrapper=wrapper

        if self.wrapper.target:
            self.log_warn("Not running website reporter because a target has been specified.")
            return

        self.keys_to_outfiles = []
        self.locations = {}

        self._navobj = Navigation()
        self._navobj.populate_lookup_table(self.wrapper.batch)
        self._navobj.walk()

        self.create_reports_dir()

        for doc in wrapper.nodes.values():
            if not doc.state in ('ran', 'consolidated'):
                continue
            if not hasattr(doc, 'output_data'):
                continue
            if not doc.output_data().output_name():
                continue

            canonical = doc.output_data().is_canonical_output()

            output_ext = doc.output_data().ext
            self.log_debug("processing %s (canonical %s)" % (doc.key, canonical))
            if canonical:
                if output_ext == ".html":
                    fragments = ('<html', '<body', '<head')
                    has_html_header = any(html_fragment in unicode(doc.output_data()) for html_fragment in fragments)

                    if doc.setting('ws-template') == False:
                        self.log_debug("  ws-template is False for %s" % doc.key)
                        self.write_canonical_data(doc)
                    elif has_html_header and not doc.setting('ws-template'):
                        self.log_debug("  found html tag in output of %s" % doc.key)
                        self.write_canonical_data(doc)
                    else:
                        self.apply_and_render_template(doc)
                elif output_ext == '.json' and 'htmlsections' in doc.key:
                    self.apply_and_render_template(doc)
                else:
                    self.write_canonical_data(doc)

        self.log_debug("finished")
