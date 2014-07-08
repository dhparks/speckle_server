### backend for iterative imaging and back-propagation interface
import time
import os
import urllib2
import datetime
import random
from speckle import io
import shutil

import server_config as sc

class BasicBackend(object):

    """ Provides methods common to the XPCS and CDI backends """

    def __init__(self, session_id, gpu_info=None):
    
        # this class receives gpu info from the flask_server, which
        # is the original instantiator of the gpu context.
        self.session_id = session_id
        self.set_gpu(gpu_info)
        
        self.data_root = sc.DATA_ROOT
        self.demo_root = sc.DEMO_ROOT
        self.allowed_exts = sc.ALLOWED_EXTS
        self.recent = sc.RECENT_DAYS
        self.upload_root = sc.UPLOAD_FOLDER
        self.data_mirror = sc.DATA_MIRROR
        self.remote_data = sc.DATA_IS_REMOTE
        
        # this dictionary tracks paths, unique-ids, and whether a local copy exists
        self.file_mirror = {}

    def set_gpu(self, gpu_info):
        """ Check the gpu"""
        if gpu_info != None:
            self.use_gpu = True
            self.gpu = gpu_info
        else:
            self.use_gpu = False

    def _new_id(self):
        """ Get a random string to use as ID; monotonic time-based"""
        # using time instead of uuid because the gui
        # needs ids that are sequential
        return str(time.time()).replace('.', '')[:12]
    
    def _new_random_id(self, length):
        """ Build a random alphanumeric string to use as id """
        chars = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j', 'k', 'l',
                 'm', 'n', 'o', 'p', 'q', 'r', 's', 't', 'u', 'v', 'w', 'x',
                 'y', 'z', 'A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J',
                 'K', 'L', 'M', 'N', 'O', 'P', 'Q', 'R', 'S', 'T', 'U', 'V',
                 'W', 'X', 'Y', 'Z', '0', '1', '2', '3', '4', '5', '6', '7',
                 '8', '9']

        return ''.join([str(random.choice(chars)) for n in range(length)])
    
    def list_directory(self, json, demo=False):
        
        """ Get directory contents from filesystem for display in the
        file-tree of the landing page """
   
        def _obscure_path(path):
            """ Hide path information before returning """
            path = path.replace(self.data_root, '$DATAROOT')
            path = path.replace(self.upload_root, '$UPLOAD')
            path = path.replace(self.demo_root, '$DEMOROOT')
            return path
            
        def _obscure_entry(entry):
            """ Hide path information before returning """
            entry = entry.replace(self.data_root, 'Beamline data')
            entry = entry.replace(self.upload_root, 'Uploaded data')
            entry = entry.replace(self.demo_root, 'Demonstration data')
            return entry
   
        def _build(**kw):
            
            """ Build the HTML string inserted into the DOM
            to expand the file-tree """
            
            if kw['t'] == 'dir':
                tmp1 = _obscure_path(kw['path'])
                tmp2 = _obscure_entry(kw['f'])
                tmp3 = '<li class="directory collapsed">\
                       <a href="#" rel="%s/">%s</a></li>'
                return tmp3%(tmp1, tmp2)
            
            if kw['t'] == 'file':
                tmp1 = kw['id']
                tmp2 = kw['ext']
                tmp3 = _obscure_path(kw['path'])
                tmp4 = kw['size']+"&nbsp;&nbsp;&nbsp;"+kw['dstr']
                tmp5 = _obscure_entry(kw['f'])
                
                fmt = "<li id='%s' class='file ext_%s'><a href='#' rel='%s'>\
                               <div class='entry'><div class='leftalign'>%s\
                               </div><div class='rightalign'>%s</div><div \
                               style='clear:both'></div></div>"
                
                return fmt%(tmp1, tmp2, tmp3, tmp5, tmp4)
            
        def _check_folder(path, entry):
            """ Helper """
            folders.append({'t':'dir',
                            'path':path,
                            'f':entry})
            
        def _check_file(path, entry):
            """ Helper """
            
            def _get_ext(entry):
                """ Check that the extension is allowed """
                try:
                    ext = os.path.splitext(entry)[1][1:]
                    if ext in self.allowed_exts:
                        return ext
                    else:
                        return None
                except:
                    return None
                
            def _get_size(entry):
                """ Get the filesize and format the string """
                num = os.path.getsize(entry)
                xnum = num
                for abrv in ('bytes', 'KB', 'MB', 'GB'):
                    if num < 1024.0:
                        return "%3.1f%s" % (num, abrv), xnum
                    num /= 1024.0
                return "%3.1f%s" % (num, 'TB'), xnum
            
            def _get_frames(f):
                """ Get the number of frames in the data """
                shape = io.get_fits_dimensions(f)
                if len(shape) == 3:
                    return shape[0]
                if len(shape) == 2:
                    return 1
                return -1
            
            def _check_mirror(path):
                """ Check if the file is in the local cache """
                if self.remote_data and self.data_root in path:
                    return os.path.isfile(path.replace(self.data_root, self.data_mirror))
                else:
                    return True

            kwords = {}

            size, bites = _get_size(path)
            kwords['t'] = 'file'
            kwords['ext'] = _get_ext(path)
            kwords['size'] = size
            kwords['bytes'] = bites
            kwords['local'] = _check_mirror(path)
            kwords['f'] = entry
            kwords['path'] = path
            kwords['date'] = os.path.getmtime(path)
            kwords['dstr'] = datetime.datetime.fromtimestamp(int(kwords['date'])).strftime('%Y-%m-%d')
            kwords['id'] = self._new_random_id(10)

            # see if this file meets the requirements
            use = True
            if kwords['ext'] == None:
                use = False
            if 'crashed' in kwords['f']:
                use = False
            
            # see if the file is recent as defined in server_config
            if recent_only and self.demo_root not in path:
                now = time.time()
                if (now-kwords['date'])/(24*3600) > self.recent:
                    use = False
                    
            if use:
                files.append(kwords)
                for_mirror[kwords['id']] = {'path':kwords['path'], \
                                            'local':kwords['local']}

        def _special_roots():
            """ The special directory command which is sent as the default
            filetree command when the landing page is building for the user.
            this reason for this command is that data_root and upload_root
            are not in the same tree. """
            _check_folder(self.demo_root, self.demo_root)
            if not demo:
                _check_folder(self.upload_root, self.upload_root)
                _check_folder(self.data_root, self.data_root)
                
        def _populate_directory(directory):
            """ Get file information about the requested directory """
            roots = [self.data_root, self.upload_root, self.demo_root]
            if sum([r in directory for r in roots]) == 0:
                directory = self.data_root
      
            # add items to r
            for entry in os.listdir(directory):
                if not entry.startswith(('.', '$')):
                    path = os.path.join(directory, entry)
                    if os.path.isdir(path):
                        _check_folder(path, entry)
                    else:
                        _check_file(path, entry)
                        
            folders.sort(key=lambda x: x['f'])
            files.sort(key=lambda x: x['f'])
            
        def _empty_directory(msg):
            """ Return this if we cant get directory information """
            tmp = ['<ul class="fileTree" style="display: none;">']
            tmp.append('Could not load directory: %s' % str(msg))
            tmp.append('</ul>')
            return {'html':''.join(tmp), 'for_mirror':for_mirror}

        directory = urllib2.unquote(json['dir'])

        # un-obscure the directory
        if '$DATAROOT' in directory:
            directory = directory.replace('$DATAROOT', self.data_root)
        if '$UPLOAD'   in directory:
            directory = directory.replace('$UPLOAD', self.upload_root)
        if '$DEMOROOT' in directory:
            directory = directory.replace('$DEMOROOT', self.demo_root)

        #recent_only = json.get('recent',False)
        
        # for now, only recent data is displayed as a soft safe-guard of data
        # the general problem is that a user using the analysis server has
        # access to anything hosted on the mirror. this problem also exists for
        # any user at the beamline.
        recent_only = True
        
        folders, files, for_mirror = [], [], {}
        
        if directory == '$ROOTS':
            _special_roots()
        
        else:
            try:
                _populate_directory(directory)

            except Exception, msg:
                return _empty_directory(msg)
                
        tmp = ['<ul class="fileTree" style="display: none;">']
        tmp += [_build(**entry) for entry in folders+files]
        tmp.append('</ul>')

        return {'html':''.join(tmp), 'for_mirror':for_mirror}
    
    def mirror_file(self, remote_name, local_name):
        """ Copy a file from remote_name (beamline computer)
        to local_name (server-hosting computer) """

        try:
            os.makedirs(os.path.split(local_name)[0])
        except:
            pass
        shutil.copy2(remote_name, local_name)

    def _flask_query(self, args, json, project):
        print "in basic query"
        to_return = {}
        to_return['sessionId'] = self.session_id
        to_return['dataId'] = self.data_id
        to_return['hasgpu'] = self.use_gpu
        to_return['size'] = self.data_size
        try:
            to_return['nframes'] = self.frames
        except:
            pass
        return to_return
