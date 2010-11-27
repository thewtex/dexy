from dexy.artifact import Artifact
from dexy.logger import log
import os
import urllib2

try:
    import json
except ImportError:
    import simplejson as json

### @export "init"
class Document(object):
    def __init__(self, name_or_key, filters = []):
        self.name = name_or_key.split("|")[0]
        self.filters = name_or_key.split("|")[1:]
        self.filters += filters
        self.inputs = []
        self.artifacts = []
        self.use_all_inputs = False

### @export "key"
    def key(self):
        return "%s|%s" % (self.name, "|".join(self.filters))

### @export "inputs"
    def add_input(self, input_doc):
        if not input_doc in self.inputs:
            self.inputs.append(input_doc)

    def finalize_inputs(self, members_dict):
        if self.use_all_inputs:
            for doc in members_dict.values():
                if not doc.use_all_inputs: # this would create mutual dependency
                    self.add_input(doc)

### @export "steps"
    def next_handler_name(self):
        if self.at_last_step():
            return 'None'
        else:
            return self.filters[self.step]
    
    def next_handler_class(self):
        if not self.at_last_step():
            return self.controller.handlers[self.next_handler_name()]

    def at_last_step(self):
        return (len(self.filters) == self.step)

### @export "input-artifacts"
    def input_artifacts(self):
        input_artifacts = {}
        for input_doc in self.inputs:
            artifact = input_doc.artifacts[-1]
            input_artifacts[input_doc.key()] = artifact.dj_filename()
        return input_artifacts

### @export "create-initial-artifact"
    def create_initial_artifact(self):
        artifact_key = self.name
        artifact = Artifact.setup(self, artifact_key, None)
        artifact.ext = os.path.splitext(self.name)[1]

        if artifact.doc.args.has_key('url'):
            url = artifact.doc.args['url']
            filename = os.path.join(self.controller.artifacts_dir, self.name)
            header_filename = "%s.headers" % filename

            if not os.path.exists(os.path.dirname(filename)):
                os.makedirs(os.path.dirname(filename))
            
            header_dict = {}
            if os.path.exists(header_filename):
                header_file = open(header_filename, "r")
                header_dict = json.load(header_file)
                header_file.close()
          
            request = urllib2.Request(url)

            # TODO add an md5 of the file to the header dict so we can check
            # that the etag/last-modified header is the corresponding one
            # TODO invalidate the hash if URL has changed

            # Add any custom headers...
            if header_dict.has_key('ETag') and os.path.exists(filename):
                request.add_header('If-None-Match', header_dict['ETag'])
            elif header_dict.has_key('Last-Modified') and os.path.exists(filename):
                request.add_header('If-Modifed-Since', header_dict['Last-Modified'])
            
            try:
                u = urllib2.urlopen(request)

                url_contents = u.read()
                
                # Save the contents in our local cache
                f = open(filename, "w")
                f.write(url_contents)
                f.close()

                # Save header info in our local cache
                header_dict = {}
                for s in u.info().headers:
                    a = s.partition(":")
                    header_dict[a[0]] = a[2].strip()
                json.dump(header_dict, open(header_filename, "w"))

                artifact.data = url_contents
            except urllib2.HTTPError as err:
                if err.code == 304:
                    print "received http status code %s, using contents of %s" % (err.code, filename)
                    f = open(filename, "r")
                    artifact.data = f.read()
                    f.close()
                else:
                    # Some other http error, we want to know about it.
                    raise err
            

        else:
            # Normal local file, just read the contents.
            f = open(self.name, "r")
            artifact.data = f.read()
            f.close()

        artifact.data_dict['1'] = artifact.data
        artifact.input_artifacts = self.input_artifacts()
        artifact.set_hashstring()
        artifact.generate()
        self.artifacts.append(artifact)
        return (artifact, artifact_key)

### @export "run"
    def run(self, controller):
        self.controller = controller
        self.step = 0
        
        artifact, artifact_key = self.create_initial_artifact()
        log.info("(step %s) %s -> %s" % (self.step, artifact_key, artifact.filename()))

        for f in self.filters:
            artifact_key += "|%s" % f
            self.step += 1
            
            if not self.controller.handlers.has_key(f):
                print self.controller.handlers.keys()
                raise Exception("""You requested filter alias '%s' but this is not available.""" % f)
            HandlerClass = self.controller.handlers[f]
            h = HandlerClass.setup(
                self, 
                artifact_key,
                artifact, 
                self.next_handler_class()
            )
            
            artifact = h.generate_artifact()
            if not artifact:
                raise Exception("no artifact created!")
            self.artifacts.append(artifact)
            
            log.info("(step %s) %s -> %s" % (self.step, artifact_key, artifact.filename()))

        return self
