from flask import Flask, jsonify, request, redirect, send_from_directory, json, session, escape, render_template
from werkzeug import secure_filename
import os
import uuid
import shutil
from os.path import getctime

import re

import time
from datetime import timedelta
import speckle, numpy

import glob
import random

app = Flask(__name__)

# if everything is present for a gpu, turn it on
try:
    import string
    import pyopencl
    import pyopencl.array as cla
    import pyfft
    use_gpu = True
except ImportError:
    use_gpu = False
    
# code for backends; gets re-instantiated for each session
from interfaces import xpcs_backend
from interfaces import imaging_backend

# concurrent user sessions are managed through a dictionary which holds
# the backends and the time of last activity
sessions = {}
def manage_session():
    # see if there is currently a session attached to the incoming request.
    # if not, assign one. the way to check for a session is to try to get a
    # key; an error indicates no session
    
    def _delete_old_files(ct):

        # define the expiration time constant
        life_hours = 8
        expired_at = time.time()-3600*life_hours
        
        # delete old files (currently they live for %life_hours% hours)
        import glob
        files, ks, ds, kept, deleted = [], [], [], 0, 0
        for path in ('static/*/images/*session*.*','static/*/csv/*session*.*','data/*session*.*'): files += glob.glob(path)
        fmt_str = r'(cdi|fth|xpcs)data_session([0-9]*)_id([0-9]*)(.*).fits'

        for f in files:
            
            # get the session id for the file
            try:
                project, session_id, data_id, extra = re.match(fmt_str,f).groups()
            except AttributeError:
                project, session_id, data_id, extra = None, None, None, None
            
            # see how old the file is. if too old, delete it.
            if getctime(f) < expired_at and extra != '_crashed':
                os.remove(f); deleted += 1; ds.append(session_id)
            else:
                kept += 1; ks.append(session_id)
                
        print "kept %s files from %s distinct sessions"%(kept,len(set(ks)))
        print "deleted %s files from %s distinct sessions"%(deleted,len(set(ds)))
        
    def _delete_old_sessions():
        # delete old sessions from the sessions dictionary. this removes the gpu
        # contexts, backends, etc.
        tx = time.time()
        session_life_hours = 8
        for sk in sessions.keys():
            if tx-sessions[sk]['last'] > 60*60*session_life_hours:
                del sessions[sk]
                
    def _make_new_session():
        
        # make a new uuid for the session
        s_id = str(time.time()).replace('.','')[:12]
        t    = int(s_id)
        
        # spin up a new gpu context and new analysis backends
        if use_gpu: gpu_info = speckle.gpu.init()
        else: gpu_info = None
        
        backendx = xpcs_backend.backend(session_id=s_id,gpu_info=gpu_info)
        backendi = imaging_backend.backend(session_id=s_id,gpu_info=gpu_info)
    
        # store these here in python; can't be serialized into the cookie!
        sessions[s_id]             = {}
        sessions[s_id]['backendx'] = backendx
        sessions[s_id]['backendi'] = backendi
        sessions[s_id]['last']     = time.time()
    
        # store these in the cookie?
        session.permanant = True
        session['s_id']   = s_id
        print "session %s"%s_id
        
        return t
        
    try:
        s_id = session['s_id']
    except KeyError:
        ct = _make_new_session()
        _delete_old_files(ct)
        _delete_old_sessions()

# functions to handle file uploading, mostly just taken from flask online documents
def allowed_file(name):
    
    ext, error, allowed = None, None, False
    
    if '.' in name:
        ext = name.rsplit('.',1)[1]
        if ext in allowed_exts:
            allowed = True
        else:
            error = "Uploaded file has wrong extension (%s). Must be .fits"%ext
    else:
        error = "Uploaded file has no extension; can't determine type"
    
    return allowed, ext, error

def get_backend(project,purge=False):
    m = {'fth':'backendi','cdi':'backendi','xpcs':'backendx'}
    try:
        backend = sessions[session['s_id']][m[project]]
        sessions[session['s_id']]['last'] = time.time()
        if project == 'xpcs' and purge: backend.regions = {}
        return backend
    except KeyError:
        return None

def error_page(kwargs):
    kwargs['img'] = random.choice(sadbabies)
    return render_template('error.html',**kwargs)

@app.route('/upload',methods=['GET','POST'])
def upload_file():

    # get (or make) the session id
    manage_session()
    s_id = session['s_id']

    # for error checking
    allowed, ext, error, backend_id = None, None, None, None
    
    if request.method == 'POST':
        project = request.files.keys()[0]
        f       = request.files[project]
        
        # check the file extension
        allowed, ext, error = allowed_file(f.filename)
        
        if allowed:
            
            filename = secure_filename(f.filename)
            save_to  = os.path.join(app.config['UPLOAD_FOLDER'], '%sdata_session%s.fits'%(project,s_id))
            f.save(save_to)
            
            # get the appropriate backend
            if project in ('cdi','fth'):
                backend = sessions[s_id]['backendi']
                backend_id = 'imaging'
                
            if project in ('xpcs',):
                backend = sessions[s_id]['backendx']
                backend.regions = {}
                backend_id = 'xpcs'
                
            # check if the data is ok. if yes, load it into the backend.
            # then, redirect the web browswer to the project page.
            checked, error = backend.check_data(save_to)
            print checked, error
            if checked:
                backend.load_data(project,app.config['UPLOAD_FOLDER'])
                return redirect('/'+project)
            
        # if we're here, there was an error with the data. do three things
        # 1. save the data for further inspection
        # 2. log the error message to a file
        # 3. generate the error page so that the user knows there is a problem
        if error != None:
            
            # 1. save the data
            new_name = save_to.replace('.fits','_crashed.fits')
            os.rename(save_to,new_name)
            
            # 2. write the error message to a file
            import datetime
            with open("data/crash_log.txt","a") as f:
                message = "time: %s\nfile: %s\naddress: %s\nbackend: %s\nmessage: %s\n\n"%(datetime.datetime.today(), new_name, request.remote_addr, backend_id, error)
                f.write(message)
                f.close()

            # 3. send the user to the error page
            kwargs = {'error':error,'backend':backend_id,'occasion':"checking the uploaded data"}
            return render_template('error.html',**kwargs)

# the rest of the decorators are switchboard functions which take a request
# and send it to the correct backend
@app.route('/')
def serve_landing():
    # now send the landing page
    return send_from_directory(".","static/html/demo.html")

@app.route('/<project>')
def serve_project(project):

    if project not in projects:
        print projects
        kwargs = {'error':"invalid project %s"%project,"occasion":"loading a project"}
        return error_page(kwargs)
    
    if project == 'xpcs':
        try:
            sessions[session['s_id']]['backendx'].regions = {}
        except KeyError:
            kwargs = {'error':'expired session','occasion':"loading a project"}
            return error_page(kwargs)
        
    return send_from_directory(".","static/html/%s.html"%project)

@app.route('/<project>/<cmd>',methods=['GET','POST'])
def dispatch_cmd(project,cmd):
    
    # dispatch commands to the backend
    backend = get_backend(project)
    if backend == None:
        error = "expired session"
        kwargs = {'error':"expired session",'occasion':'executing a command'}
        return error_page(kwargs)

    try:
        from_backend = backend.cmds[cmd](request.args,request.json,project)
        return jsonify(**from_backend)
    
    except KeyError:
        kwargs = {'error':"illegal command "+cmd,'occasion':'executing a command'}
        return error_page(kwargs)
    
@app.route('/<path:x>/sadbaby<int:y>.jpg')
def serve_sad_baby(x,y):
    return send_from_directory('.','static/error/sadbaby%s.jpg'%y)
        
allowed_exts  = set(['fits',])
app.config['UPLOAD_FOLDER'] = './data'
app.config['MAX_CONTENT_LENGTH'] = 1024**3

# for session management
import os
app.secret_key = os.urandom(24)
app.permanent_session_lifetime = timedelta(minutes=60*8)

if __name__ == '__main__':
    sadbabies = glob.glob('static/error/sadbaby*.jpg')
    projects  = [x.split('/')[-1].split('.html')[0] for x in glob.glob('static/html/*.html')]
    app.run(host="0.0.0.0",debug=False)
    