from flask import Flask, jsonify, request, redirect, send_from_directory, \
json, session, escape, render_template

import os
import uuid
from os.path import getctime

import re

import time
from datetime import timedelta
import speckle

import glob
import random

app = Flask(__name__)

# if everything is present for a gpu, turn it on
try:
    import string
    import pyopencl
    import pyopencl.array as cla
    import pyfft
    USE_GPU = True
except ImportError:
    USE_GPU = False
    
# code for backends; gets re-instantiated for each session
import server_config as config
from interfaces import xpcs_backend
from interfaces import imaging_backend

# concurrent user sessions are managed through a dictionary which holds
# the backends and the time of last activity
sessions = {}
def manage_session():
    # see if there is currently a session attached to the incoming request.
    # if not, assign one. the way to check for a session is to try to get a
    # key; an error indicates no session
    
    def _delete_old_files():
        """ Find and delete files from old sessions """

        # define the expiration time constant
        expired_at = time.time()-3600*config.LIFETIME
        
        # delete old files (currently they live for %life_hours% hours)
        files, kept_sessions, del_sessions, kept, deleted = [], [], [], 0, 0
        path1 = 'static/*/images/*session*.*'
        path2 = 'static/*/csv/*session*.*'
        path3 = config.UPLOAD_FOLDER+'/*session*.*'
        for path in (path1, path2, path3):
            files += glob.glob(path)
        fmt_str = r'(cdi|fth|xpcs)data_session([0-9]*)_id([0-9]*)(.*)\
                  .(fits|zip|csv|png|jpg)'

        for file_name in files:
            
            # get the session id for the file
            try:
                matched = re.match(fmt_str, file_name).groups()
                project, session_id, data_id, extra, fmt = matched
            except AttributeError:
                project = None
                session_id = None
                data_id = None
                extra = None
                fmt = None
            
            # see how old the file is. if too old, delete it.
            try:
                time0 = getctime(file_name)
            except OSError:
                # this error showed up in the log; not sure of cause, as
                # glob already found the file
                # and flask is blocking. error message:
                # "anaconda/lib/python2.7/genericpath.py", line 64, in getctime
                # return os.stat(filename).st_ctime
                # OSError: [Errno 2] No such file or directory:
                time0 = expired_at+1

            if time0 < expired_at and extra != '_crashed':
                os.remove(file_name)
                deleted += 1
                del_sessions.append(session_id)
            else:
                kept += 1
                kept_sessions.append(session_id)
                
        msg1 = "kept %s files from %s distinct sessions"
        msg2 = "deleted %s files from %s distinct sessions"
        print msg1%(kept, len(set(kept_sessions)))
        print msg2%(deleted, len(set(del_sessions)))
        
    def _delete_old_sessions():
        """ Delete old sessions from the sessions dict. Removes gpu
        info, backends, etc """
        time_now = time.time()
        for s_key in sessions.keys():
            if time_now-sessions[s_key]['last'] > 3600*config.LIFETIME:
                del sessions[s_key]
                
    def _make_new_session():
        """ Make a new session; instantiate new backends """
        
        # make a new uuid for the session
        s_id = str(time.time()).replace('.', '')[:12]
        int_time = int(s_id)
        
        # spin up a new gpu context and new analysis backends
        if USE_GPU:
            gpu_info = speckle.gpu.init()
        else:
            gpu_info = None
        
        backendx = xpcs_backend.Backend(session_id=s_id, gpu_info=gpu_info)
        backendi = imaging_backend.Backend(session_id=s_id, gpu_info=gpu_info)
    
        # store these here in python; can't be serialized into the cookie!
        sessions[s_id] = {}
        sessions[s_id]['file_mirror'] = {}
        sessions[s_id]['backendx'] = backendx
        sessions[s_id]['backendi'] = backendi
        sessions[s_id]['last'] = time.time()
    
        # store these in the cookie?
        session.permanant = True
        session['s_id'] = s_id
        print "session %s"%s_id
        
        return int_time
        
    try:
        s_id = session['s_id']
    except KeyError:
        new_session = _make_new_session()
        _delete_old_files()
        _delete_old_sessions()

def allowed_file(name):
    """ Check if file is allowed by examining extension """
    
    ext, error, allowed = None, None, False
    
    if '.' in name:
        ext = name.rsplit('.', 1)[1]
        if ext in config.ALLOWED_EXTS:
            allowed = True
        else:
            error = "Uploaded file has wrong extension (%s). Must be .fits"%ext
    else:
        error = "Uploaded file has no extension; can't determine type"
    
    return allowed, ext, error

def get_backend(project, purge=False):
    """ Get the backend for a project """
    backends = {'fth':'backendi', 'cdi':'backendi', 'xpcs':'backendx'}
    try:
        backend = sessions[session['s_id']][backends[project]]
        sessions[session['s_id']]['last'] = time.time()
        if project == 'xpcs' and purge:
            backend.regions = {}
        return backend
    except KeyError:
        return None

def error_page(kwargs):
    """ Return the error page """
    kwargs['img'] = random.choice(SAD_BABIES)
    return render_template('error.html', **kwargs)

@app.route('/upload', methods=['GET', 'POST'])
def upload_file():
    """ Handle file uploading to the server """

    # get (or make) the session id
    manage_session()
    s_id = session['s_id']

    # for error checking
    allowed, ext, error, backend_id = None, None, None, None
    
    if request.method == 'POST':
        project = request.files.keys()[0]
        file_obj = request.files[project]
        
        # check the file extension
        allowed, ext, error = allowed_file(file_obj.filename)
        
        if allowed:
            
            name = '%sdata_session%s.fits'%(project, s_id)
            save_to = os.path.join(config.UPLOAD_FOLDER, name)
            file_obj.save(save_to)
            
            # get the appropriate backend
            if project in ('cdi', 'fth'):
                backend = sessions[s_id]['backendi']
                backend_id = 'imaging'
                
            if project in ('xpcs',):
                backend = sessions[s_id]['backendx']
                backend.regions = {}
                backend_id = 'xpcs'
                
            # check if the data is ok. if yes, load it into the backend.
            # then, redirect the web browswer to the project page.
            checked, error = backend.check_data(save_to)
            if checked:
                backend.load_data(project, save_to)
                return redirect('/'+project)
            
        # if we're here, there was an error with the data. do three things
        # 1. save the data for further inspection
        # 2. log the error message to a file
        # 3. generate the error page so that the user knows there is a problem
        if error != None:
            
            # 1. save the data
            new_name = save_to.replace('.fits', '_crashed.fits')
            os.rename(save_to, new_name)
            
            # 2. write the error message to a file
            import datetime
            with open("data/crash_log.txt", "a") as crash_file:
                msg = "time: %s\n"%datetime.datetime.today()
                msg += "file: %s\n"%new_name
                msg += "address: %s\n"%request.remote_addr
                msg += "backend: %s\n"%backend_id
                msg += "message: %s\n\n"%error
                crash_file.write(msg)
                crash_file.close()

            # 3. send the user to the error page
            kwargs = {'error':error, 'backend':backend_id, \
                      'occasion':"checking the uploaded data",\
                      "img":random.choice(SAD_BABIES)}

            return render_template('error.html', **kwargs)

# the rest of the decorators are switchboard functions which take a request
# and send it to the correct backend
@app.route('/')
def serve_landing():
    """ Return the landing page """
    manage_session()
    return send_from_directory(".", "static/html/landing.html")

@app.route('/error', methods=['GET',])
def serve_error():
    """ Return the error page """
    kwargs = sessions[session['s_id']]['error_kwargs']
    return render_template('error.html', **kwargs)

@app.route('/filetree', methods=['POST',])
def get_directory():
    """ Return directory informatoin for the file tree"""
    manage_session()
    backend = sessions[session['s_id']]['backendi']
    from_backend = backend.list_directory(request.json)
    sessions[session['s_id']]['file_mirror'].update(from_backend['for_mirror'])
    del from_backend['for_mirror']
    return jsonify(**from_backend)

@app.route('/remoteload', methods=['POST',])
def remote_load():
    """ Take a filename from the file tree and copy
    it to local if necessary """
    
    def _manage_file():
        """ Helper: handle filemirror in backend """
        file_mirror = sessions[session['s_id']]['file_mirror']
        
        # if the requested file doesn't exist, make a copy
        jname = request.json['fileName']

        rname = file_mirror[jname]['path']
        lname = rname.replace(config.DATA_ROOT, config.DATA_MIRROR)
        
        # copy the file from remote to local
        if not file_mirror[jname]['local']:
            print "not local; copying"
            backend.mirror_file(rname, lname)
            file_mirror[jname]['local'] = True

        return lname

    # parse the json
    project = request.json['project']
    
    # get the backend
    backend = get_backend(project)
    backendi = get_backend('fth') 
    
    # figure out where the file is, and if we need to create a local copy
    local_file_name = _manage_file()
    
    # check the data. if it seems OK, load it
    # and redirect to the project page.
    checked, error = backend.check_data(local_file_name)
    if checked:
        backend.load_data(project, local_file_name)
        print "redirecting to %s"%project
        return jsonify(**{'redirect':'/'+project})
    
    else:
        
        kwargs = {'error':error, 'backend':project,
                  'occasion':"checking the uploaded data",
                  'img':random.choice(SAD_BABIES)}
        
        sessions[session['s_id']]['error_kwargs'] = kwargs
        
        return jsonify(**{'redirect':'/error'})
    
@app.route('/<project>', methods=['GET',])
def serve_project(project):
    """ Send back the project page """

    if project not in PROJECTS:
        kwargs = {'error':"invalid project %s"%project, \
                  "occasion":"loading a project"}
        return error_page(kwargs)
    
    if project == 'xpcs':
        try:
            sessions[session['s_id']]['backendx'].regions = {}
        except KeyError:
            kwargs = {'error':'expired session', 'occasion':"loading a project"}
            return error_page(kwargs)
        
    return send_from_directory(".", "static/html/%s.html"%project)

@app.route('/<project>/<cmd>', methods=['GET', 'POST'])
def dispatch_cmd(project, cmd):
    """ Send a command to the correct backend """
    
    print project, cmd
    
    # dispatch commands to the backend
    backend = get_backend(project)
    
    if backend == None:
        kwargs = {'error':"expired session", 'occasion':'executing a command'}
        return error_page(kwargs)

    try:
        from_backend = backend.cmds[cmd](request.args, request.json, project)
        return jsonify(**from_backend)
    
    except KeyError:
        occ = "executing command %s"%cmd
        kwargs = {'error':"illegal command "+cmd, 'occasion':occ}
        return error_page(kwargs)

@app.route('/<path:x>/sadbaby<int:y>.jpg')
def serve_sad_baby(x, y):
    """ Send a sadbaby photo """
    return send_from_directory('.', 'static/error/sadbaby%s.jpg'%y)
        
ALLOWED_EXTS = config.ALLOWED_EXTS
app.config['UPLOAD_FOLDER'] = config.UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = config.MAX_CONTENT_LENGTH

# for session management
app.secret_key = os.urandom(24)
app.permanent_session_lifetime = timedelta(minutes=60*8)

if __name__ == '__main__':
    SAD_BABIES = glob.glob('static/error/sadbaby*.jpg')
    
    PROJECTS = [count_file.split('/')[-1].split('.html')[0]\
                for count_file in glob.glob('static/html/*.html')]
    
    app.run(host="0.0.0.0")
    
