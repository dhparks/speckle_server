### backend for iterative imaging and back-propagation interface
import time
import os
import urllib2

import server_config as sc

class basicBackend(object):

    def __init__(self,session_id,gpu_info=None):
    
        # this class receives gpu info from the flask_server, which
        # is the original instantiator of the gpu context.
        self.session_id = session_id
        self.set_gpu(gpu_info)
        
        self.DATA_ROOT = sc.DATA_ROOT
        self.ALLOWED_EXTS = sc.ALLOWED_EXTS

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
    
    def listDirectory(self,directory):
   
        def _build(**kw):
            if kw['t'] == 'dir': return '<li class="directory collapsed"><a href="#" rel="%s/">%s</a></li>'%(kw['path'],kw['f'])
            if kw['t'] == 'file': return '<li id="%s" class="file ext_%s"><a href="#" rel="%s">%s</a></li>'%(os.path.splitext(kw['f'])[0]+str(self._new_id()),kw['ext'],kw['path'],kw['f'])
        
        def _getExt(f):
           try: 
              e = os.path.splitext(f)[1][1:]
              if e in self.ALLOWED_EXTS: return e
              else: return None
           except:
              return None
        
        r = ['<ul class="fileTree" style="display: none;">']

        try:
            r = ['<ul class="fileTree" style="display: none;">']
             
            directory = urllib2.unquote(directory)
             
            # require that d have the correct root.
            if self.DATA_ROOT not in directory.split(os.sep)[0]:
                directory = self.DATA_ROOT
      
            # add items to r
            for entry in os.listdir(directory):
                path = os.path.join(directory,entry)
                if os.path.isdir(path):
                    kw = {'t':'dir','path':path,'f':entry}
                    r.append(_build(**kw))
                else:
                    ext = _getExt(entry)
                    if ext != None and 'crashed' not in entry:
                        kw = {'t':'file','path':path,'f':entry,'ext':ext}
                        r.append(_build(**kw))
                    
            # done
            r.append('</ul>')
           
        except Exception,e:
            r.append('Could not load directory: %s' % str(e))
            r.append('</ul>')
            
        return {'html':''.join(r)}
    
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
