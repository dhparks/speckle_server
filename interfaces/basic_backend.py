### backend for iterative imaging and back-propagation interface
import time
import os
import urllib2
import datetime
import random
from speckle import io
import shutil

import server_config as sc

class basicBackend(object):

    def __init__(self,session_id,gpu_info=None):
    
        # this class receives gpu info from the flask_server, which
        # is the original instantiator of the gpu context.
        self.session_id = session_id
        self.set_gpu(gpu_info)
        
        self.DATA_ROOT = sc.DATA_ROOT
        self.DEMO_ROOT = sc.DEMO_ROOT
        self.ALLOWED_EXTS = sc.ALLOWED_EXTS
        self.RECENT = sc.RECENT_DAYS
        self.UPLOAD_ROOT = sc.UPLOAD_FOLDER
        self.DATA_MIRROR = sc.DATA_MIRROR
        self.REMOTE_DATA = sc.DATA_IS_REMOTE
        
        # this dictionary tracks paths, unique-ids, and whether a local copy exists
        self.fileMirror = {}

    def set_gpu(self,gpu_info):
        if gpu_info != None:
            self.use_gpu = True
            self.gpu     = gpu_info
        else:
            self.use_gpu = False

    def _new_id(self):
        # using time instead of uuid because the gui
        # needs ids that are sequential
        return str(time.time()).replace('.','')[:12]
    
    def _new_random_id(self,length):
        chars = ['a','b','c','d','e','f','g','h','i','j','k','l','m',
                 'n','o','p','q','r','s','t','u','v','w','x','y','z',
                 'A','B','C','D','E','F','G','H','I','J','K','L','M',
                 'N','O','P','Q','R','S','T','U','V','W','X','Y','Z',
                 '0','1','2','3','4','5','6','7','8','9']

        return ''.join([str(random.choice(chars)) for n in range(length)])
    
    def listDirectory(self,json,demo=False):
   
        def _obscurePath(p):
                p = p.replace(self.DATA_ROOT,'$DATAROOT')
                p = p.replace(self.UPLOAD_ROOT,'$UPLOAD')
                p = p.replace(self.DEMO_ROOT,'$DEMOROOT')
                return p
                
        def _obscureEntry(e):
            e = e.replace(self.DATA_ROOT,'Beamline data')
            e = e.replace(self.UPLOAD_ROOT,'Uploaded data')
            e = e.replace(self.DEMO_ROOT,'Demonstration data')
            return e
   
        def _build(**kw):
            if kw['t'] == 'dir':
                return '<li class="directory collapsed"><a href="#" rel="%s/">%s</a></li>'%(_obscurePath(kw['path']),_obscureEntry(kw['f']))
            if kw['t'] == 'file':
                
                p1 = kw['id']
                p2 = kw['ext']
                p3 = _obscurePath(kw['path'])
                p4 = kw['size']+"&nbsp;&nbsp;&nbsp;"+kw['dstr']
                p5 = _obscureEntry(kw['f'])
                
                return "<li id='%s' class='file ext_%s'><a href='#' rel='%s'><div class='entry'><div class='leftalign'>%s</div><div class='rightalign'>%s</div><div style='clear:both'></div></div>"%(p1,p2,p3,p5,p4)
            
        def _checkFolder(path,entry):
            folders.append({'t':'dir',
                            'path':path,
                            'f':entry})
            
        def _checkFile():
            
            def _getExt(f):
                try: 
                   e = os.path.splitext(f)[1][1:]
                   if e in self.ALLOWED_EXTS: return e
                   else: return None
                except:
                   return None
                
            def _getSize(f):
                num = os.path.getsize(f)
                xnum = num
                for x in ['bytes','KB','MB','GB']:
                    if num < 1024.0:
                        return "%3.1f%s" % (num, x), xnum
                    num /= 1024.0
                return "%3.1f%s" % (num, 'TB'), xnum
            
            def _getFrames(f):
                shape = io.get_fits_dimensions(f)
                if len(shape) == 3: return shape[0]
                if len(shape) == 2: return 1
                return -1
            
            def _checkMirror(path):
                if self.REMOTE_DATA and self.DATA_ROOT in path:
                    return os.path.isfile(path.replace(self.DATA_ROOT,self.DATA_MIRROR))
                else:
                    return True

            kw = {}

            s, b = _getSize(path)
            kw['t']      = 'file'
            kw['ext']    = _getExt(path)
            kw['size']   = s
            kw['bytes']  = b
            kw['local']  = _checkMirror(path)
            kw['f']      = entry
            kw['path']   = path
            kw['date']   = os.path.getmtime(path)
            kw['dstr']   = datetime.datetime.fromtimestamp(int(kw['date'])).strftime('%Y-%m-%d')
            kw['id']     = self._new_random_id(10)

            # see if this file meets the requirements
            use = True
            if kw['ext'] == None: use = False
            if 'crashed' in kw['f']: use = False
            
            # see if the file is recent as defined in server_config
            if recentOnly and self.DEMO_ROOT not in path:
                now = time.time()
                if (now-kw['date'])/(24*3600) > self.RECENT:
                    use = False
                    
            if use:
                files.append(kw)
                forMirror[kw['id']] = {'path':kw['path'],'local':kw['local']}

        directory  = urllib2.unquote(json['dir'])

        if '$DATAROOT' in directory: directory = directory.replace('$DATAROOT',self.DATA_ROOT)
        if '$UPLOAD'   in directory: directory = directory.replace('$UPLOAD',self.UPLOAD_ROOT)
        if '$DEMOROOT' in directory: directory = directory.replace('$DEMOROOT',self.DEMO_ROOT)

        #recentOnly = json.get('recent',False)
        
        # for now, only recent data is displayed as a soft safe-guard of data
        # the general problem is that a user using the analysis server has access
        # to anything hosted on the mirror. this problem also exists for any user
        # at the beamline.
        recentOnly = True
        
        folders, files, forMirror = [], [], {}
        
        if directory == '$ROOTS':
            # this is the special directory command which is sent as the default
            # filetree command when the landing page is building for the user.
            # this reason for this command is that data_root and upload_root
            # are not in the same tree
            _checkFolder(self.DEMO_ROOT,self.DEMO_ROOT)
            if not demo:
                _checkFolder(self.UPLOAD_ROOT,self.UPLOAD_ROOT)
                _checkFolder(self.DATA_ROOT,self.DATA_ROOT)
        
        else:

            try:

                # require that d have the correct root.
                roots = [self.DATA_ROOT, self.UPLOAD_ROOT, self.DEMO_ROOT]
                if sum([r in directory for r in roots]) == 0:
                    directory = self.DATA_ROOT
          
                # add items to r
                for entry in os.listdir(directory):
                    if not entry.startswith(('.','$')):
                        path = os.path.join(directory,entry)
                        if os.path.isdir(path): _checkFolder(path,entry)
                        else: _checkFile()
                            
                folders.sort(key = lambda x: x['f'])
                files.sort(key = lambda x: x['f'])
               
            except Exception,e:
                r = ['<ul class="fileTree" style="display: none;">']
                r.append('Could not load directory: %s' % str(e))
                r.append('</ul>')
                return {'html':''.join(r), 'forMirror':forMirror}
                
        r = ['<ul class="fileTree" style="display: none;">']
        r += [_build(**f) for f in folders+files]
        r.append('</ul>')

        return {'html':''.join(r),'forMirror':forMirror}
    
    def mirrorFile(self,remoteName,localName):
        # copy to mirrored directory
        try: os.makedirs(os.path.split(localName)[0])
        except: pass
        shutil.copy2(remoteName,localName)

    def _flaskQuery(self,args,json,project):
        print "in basic query"
        tr = {}
        tr['sessionId'] = self.session_id
        tr['dataId']    = self.data_id
        tr['hasgpu']    = self.use_gpu
        tr['size']      = self.data_size
        try: tr['nframes'] = self.frames
        except: pass
        return tr
