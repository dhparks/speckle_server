# server configuration options. currently the documentation is poor.

DATA_ROOT   = '/mnt/beamlinemirror' ### important! for a remote directory this should be mounted through fstab at startup
DATA_IS_REMOTE = True
DATA_MIRROR = 'data/mirror' # this mirrors data so that on repeated access it is fast
DEMO_ROOT   = 'data/demodata'
LIFETIME    = 8 # hours
UPLOAD_FOLDER = 'data/uploaded'
ALLOWED_EXTS  = set(['fits',])
MAX_CONTENT_LENGTH = 1024**3 # 1 gigabyte
RECENT_DAYS = 30
