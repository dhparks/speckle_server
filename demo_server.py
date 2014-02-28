from flask import Flask, jsonify, request, redirect, send_from_directory, json, session, escape, render_template, url_for
from werkzeug import secure_filename
import os
app = Flask(__name__)

import time
from datetime import timedelta
import speckle, numpy
import shutil
import glob
import random

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
# the backends and the time last seen
sessions = {}
def manage_session():
    # see if there is currently a session attached to the incoming request.
    # if not, assign one. the way to check for a session is to try to get a
    # key; an error indicates no session
    
    def _delete_old_files(ct):
        
        # find all candidate files
        files, locations = [], ['static/*/images/*session*.*','static/*/csv/*session*.*','data/*session*.*']
        for l in locations: files += glob.glob(l)
        kept, ks, deleted, ds = 0, [], 0, []
        
        # delete old files (files from sessions more than 8 hours old)
        life_hours = 8
        for f in files:
            try: session_id = int(f.split('_')[1].split('session')[1])
            except ValueError: session_id = int(f.split('_')[1].split('session')[1].split('.')[0])
            if ct-session_id > 10*60*60*life_hours:
                os.remove(f)
                deleted += 1
                ds.append(session_id)
            else: 
                kept += 1
                ks.append(session_id)
                
        print "kept %s files from %s sessions"%(kept,len(set(ks)))
        print "deleted %s files from %s sessions"%(deleted,len(set(ds)))
        
    def _delete_old_sessions():
        # delete old sessions from the sessions dictionary
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
        else:       gpu_info = None
        
        backendx =    xpcs_backend.backend(session_id=s_id,gpu_info=gpu_info)
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

def get_backend(project,purge=False):
    m = {'fth':'backendi','cdi':'backendi','xpcs':'backendx'}
    try:
        backend = sessions[session['s_id']][m[project]]
        sessions[session['s_id']]['last'] = time.time()
        if project == 'xpcs' and purge: backend.regions = {}
        return backend
    except KeyError:
        return None

# functions to handle file uploading, mostly just taken from flask online documents
def allowed_file(name):
    return '.' in name and name.rsplit('.', 1)[1] in allowed_exts

def error_page(kwargs):
    kwargs['img'] = random.choice(sadbabies)
    return render_template('error.html',**kwargs)

@app.route('/demo',methods=['GET',])
def upload_file():

    # get (or make) the session id
    manage_session()
    s_id = session['s_id']

    # get the project id from the request
    project = request.args['project']
    
    # move the right file from the demo folder to the upload folder
    # then run the backends in the same way as flask_server
    old_name = 'demodata/%s.fits'%project
    new_name = '%s/%sdata_session%s.fits'%(app.config['UPLOAD_FOLDER'],project,s_id)
    shutil.copy(old_name,new_name)
    print "data copied"
    
    # load the data into the correct backend
    backend = get_backend(project,purge=True)
    backend.load_data(project,app.config['UPLOAD_FOLDER'])
    
    print "about to redirect to %s"%project
    return redirect('/'+project)

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

upload_folder = './data'
allowed_exts  = set(['fits',])
app.config['UPLOAD_FOLDER'] = upload_folder
app.config['MAX_CONTENT_LENGTH'] = 1024**3 # maximum file size in bytes

# for session management
import os
app.secret_key = os.urandom(24)
app.permanent_session_lifetime = timedelta(minutes=60*8)

if __name__ == '__main__':
    sadbabies = glob.glob('static/error/sadbaby*.jpg')
    projects  = [x.split('/')[-1].split('.html')[0] for x in glob.glob('static/html/*.html')]
    app.run(host="0.0.0.0",port=5001,debug=True)
    
